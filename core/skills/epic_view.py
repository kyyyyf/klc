#!/usr/bin/env python3
"""epic_view.py — read-only epic state, dependency graph, ready-set and
validation for `klc board --epic <ROOT>` (KLC-078).

An epic is not a stored entity. It is a *computed* view over ordinary tickets
that share `meta.epic == "<ROOT>"` and carry `meta.blocked_by` dependency edges
(the schema in docs/20260724_epic_feature_impl_plan.md). This module turns a
set of member metas into:

  * the epic state — a pure function of member phases
    (all intake:* -> planned; any past intake -> in-progress;
     all archived|cancelled -> done);
  * a per-member view — current phase, unmet dependency edges, holder;
  * the ready set — members that can be picked up now (no standing unmet
    dependency and not held by another user; a held member is "occupied",
    not "ready", per the multi-user holder model);
  * validation warnings — dependency cycles (mutual blocked_by so nobody can
    start) and dangling edges (`on` is not a member / not a real ticket).

Everything here is READ-ONLY: the caller passes in already-loaded metas and this
module never touches the filesystem, never writes meta, never advances a phase.

Single resolver
---------------
"Reached the point" / "condition holds" is NOT re-implemented here. KLC-077's
`epic_deps` is the one authority for that semantics (it also backs the live
`:work` enforcement, so the view and enforcement agree by construction). This
module delegates every milestone/condition decision to
`epic_deps.reached(upstream_meta, point)` and
`epic_deps.condition_holds(cond, upstream_meta)`.

The only track-position logic kept local is `_edge_is_standing` — a downstream
"has this ticket already entered the gated phase's :work?" check that is a VIEW
concern (it decides whether an edge still matters for the ready set) and is
distinct from the upstream-milestone question epic_deps answers. It is computed
over the public `phases` ordering (the same authority epic_deps itself uses for
ordering), not a private copy of the resolver.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_skills_dir = Path(__file__).resolve().parent
if str(_skills_dir) not in sys.path:
    sys.path.insert(0, str(_skills_dir))

import phases as _phases  # noqa: E402
import holder_display  # noqa: E402
import epic_deps  # noqa: E402  (KLC-077 — the single milestone/condition resolver)
import lifecycle as _lifecycle  # noqa: E402  (shared next-:work-phase resolution)

# Epic states (never stored; computed).
STATE_PLANNED = "planned"
STATE_IN_PROGRESS = "in-progress"
STATE_DONE = "done"


# --- epic state ---------------------------------------------------------------

def epic_state(members: dict[str, dict]) -> str:
    """Pure function of member phases (never stored):
       all archived|cancelled -> done; all in intake:* -> planned;
       otherwise in-progress. Empty membership -> planned (nothing started)."""
    phase_vals = [str(m.get("phase") or "") for m in members.values()]
    if not phase_vals:
        return STATE_PLANNED
    if all(_phases.is_terminal(p) for p in phase_vals):
        return STATE_DONE
    if all(p.startswith("intake:") or p == "intake" for p in phase_vals):
        return STATE_PLANNED
    return STATE_IN_PROGRESS


# --- edges --------------------------------------------------------------------

@dataclass
class EdgeStatus:
    on: str
    phase: str            # downstream phase this edge gates
    point: str
    condition: str | None
    reached: bool         # upstream point satisfied (+ condition, if any)
    standing: bool        # still gates (downstream has not entered `phase` yet)
    dead: bool = False    # gated phase not in the downstream's track (never fires)
    note: str | None = None   # dangling / condition-failed / dead explanation

    def describe(self) -> str:
        base = f"{self.on} @ {self.point}"
        if self.condition:
            base += f":{self.condition}"
        if self.note:
            base += f" ({self.note})"
        return base


def _edge_status(edge, downstream_meta, all_metas, phase_model) -> EdgeStatus:
    """Classify one blocked_by edge of `downstream_meta`. Milestone/condition
    decisions are delegated to epic_deps (the single resolver); this only adds
    the view-time concerns of dangling / dead-edge classification and 'standing'.

    `all_metas` is EVERY repo ticket's meta (not just this epic's members) so a
    legal cross-epic `on` resolves through epic_deps exactly like the live guard;
    only an `on` absent from the whole repo is 'dangling' (MEDIUM-1)."""
    if not isinstance(edge, dict):
        return EdgeStatus(on="?", phase="?", point="?", condition=None,
                          reached=False, standing=True, note="malformed edge")
    on = edge.get("on")
    phase = edge.get("phase")
    point = edge.get("point")
    condition = edge.get("condition")

    note = None
    reached = False

    if not on or not phase or not point:
        note = "malformed edge (missing on/phase/point)"
    elif on not in all_metas:
        # Dangling ONLY when the upstream is unknown to the whole repo — a
        # cross-epic dependency on an existing ticket is legal and resolves below.
        note = "unknown ticket"
    else:
        up = all_metas[on]
        try:
            reached = epic_deps.reached(up, point)
        except ValueError:
            note = f"unknown point {point!r}"
        except Exception as exc:  # malformed upstream meta — never fatal
            note = f"unresolvable upstream ({exc.__class__.__name__})"
        if reached and condition:
            try:
                if not epic_deps.condition_holds(condition, up):
                    reached = False
                    note = f"condition {condition!r} not satisfied — human pause"
            except Exception as exc:  # corrupt phase_history etc. — never fatal
                reached = False
                note = f"condition {condition!r} unevaluable ({exc.__class__.__name__})"

    # A dead edge is fully explained by its own warning line; leave `note`
    # untouched (it stays None unless the edge is ALSO dangling/malformed) so
    # `describe()` does not double up "dead edge …".
    standing, dead = _standing_and_dead(downstream_meta, phase, phase_model)
    return EdgeStatus(on=str(on), phase=str(phase), point=str(point),
                      condition=condition, reached=reached,
                      standing=standing, dead=dead, note=note)


def _standing_and_dead(downstream_meta, gated_phase, phase_model):
    """Return (standing, dead) for an edge gating `gated_phase` of this ticket.

    standing — the edge still gates: the ticket has NOT yet entered
      `<gated_phase>:work` (the enforcement hook point). Once at or past it, the
      edge is moot. View-only, about the DOWNSTREAM ticket's own progress over
      the shared `phases.position` order — not the upstream-milestone question
      epic_deps answers, so it is not resolver duplication.
    dead — `gated_phase` is not a phase in the ticket's track, so entering it
      never happens and the live guard (`epic_deps.blocking_edges`, filtered by
      `e.phase == phase`) would never fire. Such an edge must NOT block forever;
      it is a non-firing/dead edge (KLC-078 LOW-2)."""
    track = downstream_meta.get("track")
    phase_str = str(downstream_meta.get("phase") or "")
    if _phases.is_terminal(phase_str):
        return (False, False)  # terminal: nothing pending
    if not track:
        return (True, False)   # can't place it — fail-safe pending
    seq = [p.id for p in phase_model.track_phases(track)]
    if gated_phase not in seq:
        return (False, True)   # dead edge — phase not in the track, never fires
    # A gated phase whose condition evaluates False for THIS ticket is skipped by
    # advance_to_next (same Phase.should_run), so entering it never happens — the
    # edge can never fire. Treat it as dead, matching enforcement (KLC-078 P2).
    if not phase_model.by_id(gated_phase).should_run(downstream_meta):
        return (False, True)
    cur_pos = _phases.position(track, phase_str)
    gated_pos = _phases.position(track, f"{gated_phase}:{_phases.STATE_WORK}")
    if cur_pos is None or gated_pos is None:
        return (True, False)   # can't place downstream — fail-safe pending
    return (cur_pos < gated_pos, False)


def _next_work_entry_phase(meta) -> str | None:
    """The phase whose `:work` this ticket would ENTER on its next transition —
    exactly what the live guard gates (KLC-078 P2). A dependency only bites when
    the ticket tries to ENTER the gated phase, so only an edge on THIS phase is a
    current blocker; edges on later phases are upcoming, not current.

    Delegates to `lifecycle.next_work_phase` — the SAME resolution
    `advance_to_next` uses, which honors conditional-phase skips (a phase whose
    condition is false is skipped, so the real next entry is the one after it).
    This is why we do not call `phases.next_phase` directly here: that would
    name a skipped phase as the gate and diverge from `klc next`/`ack`."""
    return _lifecycle.next_work_phase(meta)


# --- per-member view + report -------------------------------------------------

@dataclass
class MemberView:
    key: str
    phase: str
    is_root: bool
    holder: str | None
    held_by_other: bool
    status: str                       # ready | occupied | blocked | done
    unmet: list[EdgeStatus] = field(default_factory=list)      # CURRENT blockers
    upcoming: list[EdgeStatus] = field(default_factory=list)   # future-phase gates


@dataclass
class EpicReport:
    root: str
    state: str
    members: list[MemberView]
    ready: list[str]
    occupied: list[str]
    blocked: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "state": self.state,
            "members": [
                {
                    "key": m.key, "phase": m.phase, "root": m.is_root,
                    "holder": m.holder, "status": m.status,
                    "blocked_by": [e.describe() for e in m.unmet],
                    "upcoming": [f"{e.phase} <- {e.describe()}" for e in m.upcoming],
                }
                for m in self.members
            ],
            "ready": self.ready,
            "occupied": self.occupied,
            "blocked": self.blocked,
            "warnings": self.warnings,
        }


def _detect_cycles(members: dict[str, dict]) -> list[str]:
    """Directed-cycle detection over the dependency graph. An edge on->key
    means `key` is blocked_by `on`; a cycle is a set of members that all wait on
    each other so nobody can start. Only edges between members count."""
    adj: dict[str, set[str]] = {k: set() for k in members}
    for key, meta in members.items():
        for edge in (meta.get("blocked_by") or []):
            if isinstance(edge, dict):
                on = edge.get("on")
                if on in members:
                    adj[key].add(on)   # key depends on on

    warnings: list[str] = []
    seen_cycle_sets: set[frozenset] = set()
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in members}

    def dfs(node: str, stack: list[str]) -> None:
        color[node] = GREY
        stack.append(node)
        for nxt in sorted(adj[node]):
            if color[nxt] == GREY:
                # back-edge -> cycle from nxt..node
                idx = stack.index(nxt)
                cycle = stack[idx:]
                key = frozenset(cycle)
                if key not in seen_cycle_sets:
                    seen_cycle_sets.add(key)
                    chain = " -> ".join(cycle + [nxt])
                    warnings.append(
                        f"cycle: {chain} (mutual blocked_by; nobody can start)")
            elif color[nxt] == WHITE:
                dfs(nxt, stack)
        stack.pop()
        color[node] = BLACK

    for k in sorted(members):
        if color[k] == WHITE:
            dfs(k, [])
    return warnings


def compute_epic(root: str, all_metas: dict[str, dict],
                 *, me: str | None = None, phase_model=None) -> EpicReport:
    """Build the full read-only epic report.

    all_metas — {key: meta} for EVERY ticket in the repo. Membership is computed
                here (`meta.epic == root`); the full set is also what upstream
                edges resolve against, so a legal cross-epic `on` is honoured
                like the live guard and only a repo-unknown `on` is dangling.
    me        — current user identity; a member held by anyone else is "occupied".
    """
    if phase_model is None:
        phase_model = _phases.load_phases()
    members = {k: m for k, m in all_metas.items() if m.get("epic") == root}

    state = epic_state(members)
    warnings: list[str] = _detect_cycles(members)

    views: list[MemberView] = []
    ready: list[str] = []
    occupied: list[str] = []
    blocked: list[str] = []

    for key in sorted(members):
        meta = members[key]
        phase_str = str(meta.get("phase") or "?")
        is_root = (meta.get("epic") == key)
        holder = holder_display.holder_label(meta)
        held_other = bool(holder and me is not None and holder != me)
        # When identity is unknown (me is None) any holder counts as "someone",
        # so an occupied ticket is never mis-reported as ready.
        if holder and me is None:
            held_other = True

        edge_statuses = [
            _edge_status(e, meta, all_metas, phase_model)
            for e in (meta.get("blocked_by") or [])
        ]
        for es in edge_statuses:
            if es.dead:
                warnings.append(
                    f"dead edge: {key} blocked_by -> {es.describe()} "
                    f"(phase {es.phase!r} never entered on {key}'s track — "
                    f"skipped or not applicable — never fires)")
            elif es.note and (
                "unknown ticket" in es.note
                or "malformed" in es.note
                or es.note.startswith("unknown point")
            ):
                warnings.append(f"dangling: {key} blocked_by -> {es.describe()}")

        # Align with the live guard: an unmet edge is a CURRENT blocker only when
        # it gates the ticket's IMMEDIATE next `:work` entry (KLC-078 P2). Unmet
        # edges that still stand but gate a LATER phase are 'upcoming' — they do
        # NOT drop the member from the ready set (early-phase work is actionable).
        next_entry = _next_work_entry_phase(meta)
        pending = [e for e in edge_statuses
                   if e.standing and not e.dead and not e.reached]
        unmet = [e for e in pending if e.phase == next_entry]
        upcoming = [e for e in pending if e.phase != next_entry]

        terminal = _phases.is_terminal(phase_str)
        if terminal:
            status = "done"
        elif unmet:
            status = "blocked"
            blocked.append(key)
        elif held_other:
            status = "occupied"
            occupied.append(key)
        else:
            status = "ready"
            ready.append(key)

        views.append(MemberView(
            key=key, phase=phase_str, is_root=is_root, holder=holder,
            held_by_other=held_other, status=status, unmet=unmet,
            upcoming=upcoming,
        ))

    return EpicReport(
        root=root, state=state, members=views, ready=ready,
        occupied=occupied, blocked=blocked, warnings=warnings,
    )


# --- text render --------------------------------------------------------------

def render_text(report: EpicReport) -> str:
    lines: list[str] = []
    lines.append(f"== epic {report.root} — {report.state} ({len(report.members)} members) ==")
    lines.append("")
    lines.append("members:")
    for m in report.members:
        root_tag = "  (root)" if m.is_root else ""
        held = f"  held by {m.holder}" if m.holder else ""
        block = ""
        if m.unmet:
            block = "  blocked by " + "; ".join(e.describe() for e in m.unmet)
        upcoming = ""
        if m.upcoming:
            upcoming = "  upcoming gate: " + "; ".join(
                f"{e.phase} <- {e.describe()}" for e in m.upcoming)
        lines.append(f"  {m.key:<10} {m.phase:<20}{root_tag}{block}{upcoming}{held}")

    lines.append("")
    lines.append("ready set:")
    if report.ready:
        for k in report.ready:
            lines.append(f"  {k}")
    else:
        lines.append("  (none)")

    if report.occupied:
        lines.append("")
        lines.append("occupied (held by others):")
        for m in report.members:
            if m.status == "occupied":
                lines.append(f"  {m.key}  held by {m.holder}")

    if report.blocked:
        lines.append("")
        lines.append("blocked:")
        for m in report.members:
            if m.status == "blocked":
                reasons = "; ".join(e.describe() for e in m.unmet)
                lines.append(f"  {m.key}  waiting on {reasons}")

    if report.warnings:
        lines.append("")
        lines.append("!! validation warnings")
        for w in report.warnings:
            lines.append(f"  {w}")

    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("epic_view.py is a library module; import it, don't run it")
