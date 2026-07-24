#!/usr/bin/env python3
"""epic_deps.py — the epic dependency resolver (KLC-077).

An epic is not a stored entity: it is three pieces of data on ordinary tickets
(see docs/20260724_epic_feature_impl_plan.md). This module is the pure logic that
answers, for a DOWNSTREAM ticket about to enter a `:work` phase, "is that phase
blocked by an upstream ticket that has not yet reached the required milestone?".

Schema (all on normal ticket meta.json, ridden by the existing per-ticket
`state_tx` — no new coordination surface):

  meta.epic        — the epic ROOT ticket key (a string; the root points at
                     itself). Grouping only, never enforcement.
  meta.blocked_by  — a list of dependency EDGES on the DOWNSTREAM ticket, each:
                       {"on": "<KEY>", "phase": "<downstream-phase-id>",
                        "point": "design-accepted|integrated|archived",
                        "condition"?: "passed"}
                     `phase` is the downstream phase whose `:work` entry the edge
                     gates; `point` is the upstream milestone that must be reached
                     first; `condition` is an optional predicate on the upstream
                     outcome.

The resolver is deliberately pure over meta dicts plus a caller-supplied
`read_upstream_meta(key) -> dict|None` reader, so it is trivially testable and it
never itself touches git or the filesystem. `default_upstream_reader()` is the
CLI convenience that reads the real on-disk upstream meta read-only.

Enforcement is a SINGLE choke point: `lifecycle.enter_work_guard` calls
`is_blocked` right before any `:work`-entry write, INSIDE the verb's `state_tx`
(post-pull), and raises `BlockedError` if blocked. Ordering is delegated to
`phases.py` (config/phases.yml) — the "reached the point" check is a monotonic
position comparison over the upstream's track, never a hardcoded phase list.
"""
from __future__ import annotations

from dataclasses import dataclass

import phases as _ph


# --- vocabulary (the shared contract) ----------------------------------------

# Upstream milestones a downstream edge can wait on.
POINTS = ("design-accepted", "integrated", "archived")
# v1 condition predicates. Absent = unconditional; unknown at runtime → treated
# as not-holding (safe: blocks and asks for a human) — but rejected at intake.
CONDITIONS = ("passed",)

# `<phase>:<state>` positions inside a track: work < ack-needed < ack.
_STATE_ORDER = {
    _ph.STATE_WORK: 0,
    _ph.STATE_ACK_NEEDED: 1,
    _ph.STATE_ACK: 2,
}
# `archived` sits past every real phase-state; `cancelled` is a dead-end that
# reaches no real milestone (see _position()).
_ARCHIVED_POS = 10 ** 6

# STRUCTURED phase_history signals that taint a `passed` condition (LOW-3): the
# entry's `event` type and the recorded `pick.label` — never a substring scan of
# the free-text `note` (which over-blocks "regression tests" and under-blocks a
# rework recorded only as event="jump").
#   abort / cancelled  — the phase was torn down;
#   jump               — a (backward) jump is a rework signal;
#   pick regression/rollback — the observe phase found a defect after integrate.
_TAINT_EVENTS = ("abort", "cancelled", "jump")
_TAINT_PICK_LABELS = ("regression", "rollback")


def _entry_pick_label(entry: dict) -> str | None:
    """The pick label recorded on a phase_history entry, or None.

    Prefers the STRUCTURED `entry["pick"]["label"]` (KLC-077 LOW-3). For entries
    written BEFORE that field existed, falls back to the recognised legacy note
    shape only — `pick=<id>:<label>` or `pick=<label>` (P1-A) — NOT an arbitrary
    substring scan, so a benign note ("added regression tests") never taints.
    """
    pick = entry.get("pick")
    if isinstance(pick, dict):
        return pick.get("label")
    note = (entry.get("note") or "").strip()
    if note.startswith("pick="):
        token = note[len("pick="):].strip()
        return token.split(":", 1)[1].strip() if ":" in token else token
    return None


# --- exceptions ---------------------------------------------------------------

class UpstreamUnreadable(Exception):
    """The upstream ticket exists but its meta.json could not be read/parsed —
    distinct from a MISSING upstream (which is 'dangling')."""


class BlockedError(Exception):
    """Raised by `lifecycle.enter_work_guard` when entering a `:work` phase is
    blocked by an unmet dependency edge. Carries the `BlockedEdge` as `.edge`;
    verbs translate it to a friendly refusal, the autorunner to a clean pause."""

    def __init__(self, edge: "BlockedEdge"):
        super().__init__(edge.message())
        self.edge = edge


# --- point → upstream phase-state --------------------------------------------

def point_to_phase_state(point: str, upstream_track: str) -> str:
    """Resolve a dependency `point` to the upstream phase-state it requires,
    against the upstream ticket's track. Raises ValueError on an unknown point.

    | point           | upstream phase-state                            |
    |-----------------|-------------------------------------------------|
    | design-accepted | design:ack (M/L)  or  discovery-lite:ack (XS/S) |
    | integrated      | integrate:ack                                   |
    | archived        | archived                                        |
    """
    if point == "design-accepted":
        if upstream_track in ("XS", "S"):
            return "discovery-lite:ack"
        return "design:ack"          # M / L (and any non-XS/S default)
    if point == "integrated":
        return "integrate:ack"
    if point == "archived":
        return _ph.STATE_ARCHIVED
    raise ValueError(
        f"unknown dependency point {point!r}; expected one of {POINTS}"
    )


# --- position + reached() -----------------------------------------------------

def _position(track: str, phase_state: str) -> int | None:
    """A comparable integer position for `phase_state` within `track`.

    Returns None when the position is unresolvable/meaningless:
      - `cancelled` (terminated early — reaches no real milestone);
      - a phase not applicable to the track;
      - a malformed state string.
    `archived` returns a sentinel past every real phase-state.
    """
    if phase_state == _ph.STATE_ARCHIVED:
        return _ARCHIVED_POS
    if phase_state == _ph.STATE_CANCELLED:
        return None
    try:
        pid, st = _ph.parse_state(phase_state)
    except ValueError:
        return None
    seq = [p.id for p in _ph.load_phases().track_phases(track)]
    if pid not in seq:
        return None
    return seq.index(pid) * 3 + _STATE_ORDER.get(st, 0)


def reached(upstream_meta: dict, point: str) -> bool:
    """True iff the upstream ticket's current phase is AT OR PAST the phase-state
    that `point` requires — a monotonic position check over config/phases.yml,
    resolved against the upstream ticket's own track."""
    track = upstream_meta.get("track") or "M"
    target = point_to_phase_state(point, track)
    cur_pos = _position(track, upstream_meta.get("phase", ""))
    tgt_pos = _position(track, target)
    if cur_pos is None or tgt_pos is None:
        return False
    return cur_pos >= tgt_pos


# --- condition_holds() --------------------------------------------------------

def condition_holds(cond: str, upstream_meta: dict) -> bool:
    """Evaluate a v1 edge condition against the upstream ticket.

    `passed` holds iff the upstream shows no rollback / abort / regression / jump
    signal in its phase_history (and no `regression_observed` / `cancelled`
    marker). The caller checks `reached()` first, so "point reached" is already
    guaranteed when this runs; this only verifies the outcome was clean.

    Detection is STRUCTURED (LOW-3): the entry `event` type and the recorded
    `pick.label`, not a substring scan of the free-text `note`. v1 simplification:
    the whole phase_history is scanned (a safe superset of "up to that point").
    Any UNKNOWN condition returns False — a failed/unknown condition is meant to
    STOP for a human, so not-holding is the safe answer.
    """
    if cond != "passed":
        return False
    if upstream_meta.get("cancelled"):
        return False
    if upstream_meta.get("regression_observed") == 1:
        return False
    for entry in upstream_meta.get("phase_history") or []:
        if (entry.get("event") or "") in _TAINT_EVENTS:
            return False
        if _entry_pick_label(entry) in _TAINT_PICK_LABELS:
            return False
    return True


# --- edge selection + is_blocked() -------------------------------------------

@dataclass
class BlockedEdge:
    """A single unmet dependency edge, with the reason it is unmet."""
    on: str
    point: str
    phase: str
    condition: str | None
    reason: str          # not-reached | condition-failed | dangling |
    #                      cancelled | unreadable

    def message(self) -> str:
        if self.reason == "dangling":
            return (f"blocked by {self.on} — upstream ticket not found "
                    f"(dangling dependency); a human must fix the edge")
        if self.reason == "unreadable":
            return (f"blocked by {self.on} — upstream meta.json is "
                    f"unreadable/corrupt; a human must check it")
        if self.reason == "cancelled":
            return (f"blocked by {self.on} — cancelled, will not reach "
                    f"{self.point} (needs a human)")
        if self.reason == "condition-failed":
            return (f"blocked by {self.on} at {self.point}: upstream condition "
                    f"{self.condition!r} not satisfied "
                    f"(rollback/regression/abort/jump upstream) — needs a human")
        return f"blocked by {self.on} until {self.point}"


def blocking_edges(meta: dict, phase: str) -> list[dict]:
    """The edges in `meta.blocked_by` that gate entering `phase`'s `:work`."""
    edges = meta.get("blocked_by") or []
    return [e for e in edges
            if isinstance(e, dict) and e.get("phase") == phase]


def is_blocked(meta: dict, phase: str, read_upstream_meta) -> BlockedEdge | None:
    """Return the FIRST unmet edge gating `phase`, or None if entry is allowed.

    `read_upstream_meta(key)` returns the upstream ticket's meta dict, or None if
    the ticket does not exist; it may raise `UpstreamUnreadable` if the ticket
    exists but is corrupt. Reasons:
      - dangling         — missing upstream (unsatisfiable);
      - unreadable       — corrupt upstream meta (unsatisfiable);
      - cancelled        — upstream terminated early, will never reach the point;
      - not-reached      — upstream is short of the point;
      - condition-failed — reached, but the edge condition does not hold.
    Empty/absent `blocked_by` → no edges → None (a pure no-op for non-epic
    tickets)."""
    for edge in blocking_edges(meta, phase):
        on = edge.get("on")
        point = edge.get("point")
        cond = edge.get("condition")
        if not on:
            return BlockedEdge(on, point, phase, cond, "dangling")
        try:
            up = read_upstream_meta(on)
        except UpstreamUnreadable:
            return BlockedEdge(on, point, phase, cond, "unreadable")
        if up is None:
            return BlockedEdge(on, point, phase, cond, "dangling")
        try:
            ok = reached(up, point)
        except ValueError:
            ok = False        # malformed/unknown point on a hand-edited meta
        if not ok:
            reason = ("cancelled"
                      if up.get("phase") == _ph.STATE_CANCELLED
                      else "not-reached")
            return BlockedEdge(on, point, phase, cond, reason)
        if cond and not condition_holds(cond, up):
            return BlockedEdge(on, point, phase, cond, "condition-failed")
    return None


# --- --blocked-by spec parsing ------------------------------------------------

def parse_edge(spec: str, self_key: str | None = None) -> dict:
    """Parse a `--blocked-by` CLI spec into a `blocked_by` edge dict.

    Grammar:  <KEY>@<point>[:<condition>]#<downstream-phase>
    Examples: KLC-077@design-accepted#design
              KLC-077@integrated:passed#build

    Validates the shape, the `point` vocabulary, the `condition` vocabulary (when
    present), and — when `self_key` is given — rejects a self-reference edge (a
    trivial 1-node cycle). Raises ValueError (hard-fail) on anything malformed.
    The downstream `phase` is NOT validated against config/phases.yml here (kept
    config-free for unit testing); the intake CLI does that additional check."""
    raw = (spec or "").strip()
    if "#" not in raw or "@" not in raw:
        raise ValueError(
            f"bad --blocked-by {spec!r}: expected "
            f"'<KEY>@<point>[:<cond>]#<phase>'"
        )
    left, phase = raw.rsplit("#", 1)
    on, point_spec = left.split("@", 1)
    on = on.strip()
    phase = phase.strip()
    point_spec = point_spec.strip()
    if not on or not phase or not point_spec:
        raise ValueError(
            f"bad --blocked-by {spec!r}: empty key/point/phase; expected "
            f"'<KEY>@<point>[:<cond>]#<phase>'"
        )
    if self_key is not None and on == self_key:
        raise ValueError(
            f"bad --blocked-by {spec!r}: self-reference — {on} cannot depend on "
            f"itself (a 1-node cycle)"
        )
    if ":" in point_spec:
        point, cond = point_spec.split(":", 1)
        point = point.strip()
        cond = cond.strip()
    else:
        point, cond = point_spec, None
    if point not in POINTS:
        raise ValueError(
            f"bad --blocked-by {spec!r}: unknown point {point!r}; "
            f"expected one of {POINTS}"
        )
    edge = {"on": on, "point": point}
    if cond is not None:
        if cond not in CONDITIONS:
            raise ValueError(
                f"bad --blocked-by {spec!r}: unknown condition {cond!r}; "
                f"expected one of {CONDITIONS}"
            )
        edge["condition"] = cond
    edge["phase"] = phase
    return edge


# --- CLI convenience: read real on-disk upstream metas (read-only) -----------

def default_upstream_reader():
    """A `read_upstream_meta(key)` that reads the real on-disk upstream meta
    READ-ONLY (never persists a legacy migration, so checking a block never
    dirties another ticket's tree). Returns None for a MISSING ticket, and
    raises `UpstreamUnreadable` for one that exists but is corrupt (LOW-5)."""
    import lifecycle as _lc

    def _read(key: str):
        try:
            return _lc.read_meta_ro(key)
        except FileNotFoundError:
            return None
        except Exception as exc:
            raise UpstreamUnreadable(f"{key}: {exc}")
    return _read
