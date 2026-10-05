#!/usr/bin/env python3
"""`klc status <ticket>` — the ticket's facts and its next move (KLC-179).

One line per fact the ticket's lane requires (✓ done, · pending), the position
(`← now`, with the exact sub-state and holder), the `blocked_on` decision when a
human pick is needed, and the next move from the rule table:

  KLC-123  track=S  lane=light  kind=tech

    ✓ spec_approved
    ✓ plan_reviewed
    · steps_green
    · review_verdict
    · merged
    ● build  ← now · work (step 2/4)
    next move: build (missing fact: steps_green)

The last line is the same next-action line `klc go --dry-run` prints.
Facts come from `meta.facts`; an older meta without them is derived in memory
by `rules.derive_facts` (status never writes).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import holder_display  # noqa: E402
import rules as _rules  # noqa: E402  KLC-179: facts + rule table
import next_move as _next_move  # noqa: E402  KLC-177: shared next-action line
import artefacts as _artefacts  # noqa: E402  KLC-118: one card-path resolver
import advisories as _advisories  # noqa: E402  KLC-117: read-only artifact display


FACT_DONE     = "✓"
FACT_PENDING  = "·"
BOX_DONE      = "[✓]"  # ✓
BOX_CURRENT   = "[●]"  # ●
BOX_EMPTY     = "[ ]"
BOX_CANCELLED = "[✗]"  # ✗ — terminated early (KLC-076)


def _meta(ticket: str) -> dict | None:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        return None
    try:
        # Read-only: migrate a legacy phase in-memory for display, but never
        # write it back — status must not dirty the tree (KLC-062 AC-2).
        return _lc.read_meta_ro(ticket)
    except FileNotFoundError:
        return None


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc status", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    args = ap.parse_args(argv)

    meta = _meta(args.ticket)
    if meta is None:
        sys.stderr.write(
            f"klc status: unknown ticket {args.ticket!r}; "
            f"run `klc intake {args.ticket}` or `klc board`\n"
        )
        return 1

    track = meta.get("track") or "M"
    kind = meta.get("kind") or "?"
    phase_value = meta.get("phase") or ""
    lane = _rules.lane_of(meta)
    tags = meta.get("risk_tags")
    facts = _rules.derive_facts(meta, _ticket_dir(args.ticket))
    move = _rules.next_move(facts, lane, risk_tags=tags)
    required = _rules.required_facts(facts, lane, risk_tags=tags)

    if args.json:
        view = {"facts": facts, "lane": lane, "blocked_on": move.blocked_on,
                "next_move": asdict(move)}
        for key in ("review_override", "integrate"):          # R2-003: overrides stay visible
            if meta.get(key):
                view[key] = meta[key]
        # Terminal pseudo-states (archived/cancelled) own no phase — special-case
        # BEFORE parse_state, which would otherwise treat them as active (KLC-076).
        if _ph.is_terminal(phase_value):
            print(json.dumps({"ticket": args.ticket, "phase": phase_value,
                              "track": track, "kind": kind,
                              "phase_id": phase_value, "state": phase_value, **view}))
            return 0
        try:
            cur_pid, cur_state = _ph.parse_state(phase_value)
        except ValueError:
            sys.stderr.write(
                f"klc status: meta.json:phase is unparseable: {phase_value!r}\n"
            )
            return 1
        out = {"ticket": args.ticket, "phase": phase_value,
              "track": track, "kind": kind,
              "phase_id": cur_pid, "state": cur_state, **view}
        adv = _advisories.for_display(args.ticket, cur_pid)
        if adv is not None:
            out["advisories"] = adv
        print(json.dumps(out))
        return 0

    print(f"{args.ticket}  track={track}  lane={lane}  kind={kind}")
    print()

    if phase_value == _ph.STATE_ARCHIVED:
        for name in required:
            print(f"  {FACT_DONE} {name}")
        print(f"  {BOX_DONE} archived")
        return 0

    # Cancelled is terminal but NOT done: don't paint the facts green. Show a
    # single cancelled row (with the reason / originating phase, if recorded) so
    # it renders without error and never reads as active/complete (KLC-076).
    if phase_value == _ph.STATE_CANCELLED:
        print(f"  {BOX_CANCELLED} cancelled — ticket terminated (will not be done)")
        reason = meta.get("cancel_reason")
        if reason:
            print(f"      reason: {reason}")
        from_phase = _cancelled_from_phase(meta)
        if from_phase:
            print(f"      cancelled from: {from_phase}")
        return 0

    try:
        cur_pid, cur_state = _ph.parse_state(phase_value)
    except ValueError:
        sys.stderr.write(
            f"klc status: meta.json:phase is unparseable: {phase_value!r}\n"
        )
        return 1

    for name in required:
        print(f"  {FACT_DONE if _rules.holds(facts, name) else FACT_PENDING} {name}")
    phase = _ph.load_phases().by_id(cur_pid)
    print(f"  {BOX_CURRENT} {cur_pid:<22} ← now · {_annotate_current(phase, cur_state, meta)}")
    if move.blocked_on:
        print(f"  blocked_on: {move.blocked_on}  (a human decision: --pick N)")
    print(f"  next move: {move.action}" + (f" ({move.reason})" if move.reason else ""))
    # R2-003: a human override is recorded in meta; show it so it is not invisible.
    override = meta.get("review_override")
    if override:
        print(f"  review: approved by override over {override.get('report_verdict') or '?'}"
              f" at {override.get('at') or '?'}")
    if (meta.get("integrate") or {}).get("confirmed_by_pick"):
        print("  integrate: merge confirmed by pick (not verified against main)")

    # Advisory records (KLC-117 AC-13): high/medium in full, the rest as a count.
    adv = _advisories.for_display(args.ticket, cur_pid)
    if adv and (adv["high"] or adv["medium"] or adv["other_count"]):
        print()
        for r in adv["high"] + adv["medium"]:
            print(f"  [{r.get('severity', '?')}] {r.get('message', '')}")
        if adv["other_count"]:
            print(f"  ...and {adv['other_count']} more (see the ticket's advisories.json)")

    # Next-action hint.
    print()
    hint = _next_hint(args.ticket, cur_pid, cur_state, meta)
    print(hint)
    return 0


def _ticket_dir(ticket: str):
    return klc_ticket_meta_file(ticket).parent


def _cancelled_from_phase(meta: dict) -> str | None:
    """The phase a cancelled ticket was terminated from, recorded on the
    `cancelled` phase_history entry (KLC-076). None if unavailable."""
    for entry in reversed(meta.get("phase_history") or []):
        if entry.get("event") == "cancelled":
            return entry.get("from_phase")
    return None


def _annotate_current(phase: _ph.Phase, state: str, meta: dict) -> str:
    base = _annotate_state(phase, state, meta)
    wait = holder_display.waiting_hint(meta, state)
    if wait:
        return f"{base} · {wait}"
    label = holder_display.holder_label(meta)
    if label:
        return f"{base} · held by {label}"
    return base


def _annotate_state(phase: _ph.Phase, state: str, meta: dict) -> str:
    if state == _ph.STATE_WORK:
        # Build-specific: show step progress if meta tracks it.
        step = meta.get("impl_step")
        total = meta.get("impl_step_total")
        if phase.id == "build" and step is not None:
            if total is not None:
                return f"work (step {step}/{total})"
            return f"work (step {step})"
        return "work"
    if state == _ph.STATE_ACK_NEEDED:
        if phase.pick_required and phase.picks:
            opts = ", ".join(f"{pk.id}={pk.label}" for pk in phase.picks)
            return f"ack-needed · pick required ({opts})"
        return "ack-needed"
    if state == _ph.STATE_ACK:
        return "ack"
    return state


def _next_hint(ticket: str, cur_pid: str, cur_state: str, meta: dict) -> str:
    """The last line of `klc status`: the same line `klc go --dry-run` prints.

    Both come from `next_move.render`, so the two can never disagree."""
    try:
        return _next_move.render(_next_move.compute(ticket))
    except Exception:
        return ""


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
