#!/usr/bin/env python3
"""lifecycle.py — ticket phase state machine.

Each ticket's meta.json carries a `phase` field. Phase values and
transitions are enumerated here so phase scripts cannot accidentally
jump forward (e.g. `klc build` after `klc intake` without discovery).

Phases follow process-phases.md §1:

    intake              → discovery-running
    discovery-running   → discovery-pending-ack
    discovery-pending-ack → test-plan-pending | build-pending   (XS skips test-plan)
    test-plan-pending   → design-pending       | build-pending  (XS/S may skip design)
    design-pending      → design-pending-ack
    design-pending-ack  → build-pending
    build-pending       → review-pending
    review-pending      → review-pending-ack
    review-pending-ack  → manual-pending       | integrate-pre  (manual may be skipped)
    manual-pending      → manual-pending-ack
    manual-pending-ack  → integrate-pre
    integrate-pre       → integrate-post
    integrate-post      → observe              | learn          (observe may be skipped)
    observe             → learn
    learn               → archived

`klc back` writes audit entries and walks backwards; no regular phase
command may move backward.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import klc_ticket_meta_file  # noqa: E402


PHASES: list[str] = [
    "intake",
    "discovery-running",
    "discovery-pending-ack",
    "test-plan-pending",
    "design-pending",
    "design-pending-ack",
    "detailed-test-plan-pending",
    "build-pending",
    "review-pending",
    "review-pending-ack",
    "manual-pending",
    "manual-pending-ack",
    "integrate-pre",
    "integrate-post",
    "observe",
    "learn",
    "archived",
]

# Forward-only transitions. `back` is a separate command, not a
# transition — it writes an audit entry and may jump to any earlier
# phase from the graph below.
TRANSITIONS: dict[str, set[str]] = {
    "intake":                 {"discovery-running"},
    "discovery-running":      {"discovery-pending-ack"},
    "discovery-pending-ack":  {"test-plan-pending", "build-pending"},
    # Acceptance test plan — S jumps straight to Build (no design);
    # M / L go to Design next.
    "test-plan-pending":      {"design-pending", "build-pending"},
    "design-pending":         {"design-pending-ack"},
    # After Design ack (M / L) comes the detailed test plan. Build
    # never follows Design directly — the detailed phase is the gate.
    "design-pending-ack":     {"detailed-test-plan-pending"},
    "detailed-test-plan-pending": {"build-pending"},
    "build-pending":          {"review-pending"},
    "review-pending":         {"review-pending-ack"},
    "review-pending-ack":     {"manual-pending", "integrate-pre"},
    "manual-pending":         {"manual-pending-ack"},
    "manual-pending-ack":     {"integrate-pre"},
    "integrate-pre":          {"integrate-post"},
    "integrate-post":         {"observe", "learn"},
    "observe":                {"learn"},
    "learn":                  {"archived"},
    "archived":               set(),
}


def read_meta(ticket_id: str) -> dict:
    p = klc_ticket_meta_file(ticket_id)
    if not p.exists():
        raise FileNotFoundError(
            f"ticket {ticket_id!r} has no meta.json; run `klc intake` first"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def write_meta(ticket_id: str, meta: dict) -> None:
    p = klc_ticket_meta_file(ticket_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")


def current_phase(ticket_id: str) -> str:
    return read_meta(ticket_id).get("phase", "intake")


def can_enter(current: str, target: str) -> bool:
    """True iff target is a legal forward transition from current."""
    if current == target:
        return True  # re-running the current phase is always allowed
    return target in TRANSITIONS.get(current, set())


def advance(ticket_id: str, target: str, *, note: str = "") -> None:
    """Move the ticket to `target`. Raises if the transition is illegal.
    Appends to `phase_history` with timestamps for the timeline used by
    Learn / metrics."""
    meta = read_meta(ticket_id)
    cur = meta.get("phase", "intake")
    if not can_enter(cur, target):
        raise ValueError(
            f"illegal transition {cur!r} → {target!r} for ticket {ticket_id!r}. "
            f"allowed from {cur!r}: {sorted(TRANSITIONS.get(cur, set())) or ['(none)']}"
        )
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    history = meta.setdefault("phase_history", [])
    # close previous open entry
    if history and "finished_at" not in history[-1]:
        history[-1]["finished_at"] = now
    history.append({"phase": target, "started_at": now, "note": note or None})
    meta["phase"] = target
    write_meta(ticket_id, meta)


def back(ticket_id: str, target: str, *, reason: str) -> None:
    """Rework jump. Target must be earlier than current in the linear
    ordering; rework_count increments on the source phase."""
    if not reason.strip():
        raise ValueError("back requires a non-empty reason")
    meta = read_meta(ticket_id)
    cur = meta.get("phase", "intake")
    try:
        cur_idx = PHASES.index(cur)
        tgt_idx = PHASES.index(target)
    except ValueError as exc:
        raise ValueError(f"unknown phase: {exc}")
    if tgt_idx >= cur_idx:
        raise ValueError(
            f"`back` target must precede current phase; got {target!r} "
            f"(idx {tgt_idx}) ≥ {cur!r} (idx {cur_idx})"
        )
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    history = meta.setdefault("phase_history", [])
    if history and "finished_at" not in history[-1]:
        history[-1]["finished_at"] = now
    history.append({
        "phase":       target,
        "started_at":  now,
        "from":        cur,
        "reason":      reason,
        "event":       "back",
    })
    rework = meta.setdefault("rework_count", {})
    rework[cur] = int(rework.get(cur, 0)) + 1
    meta["phase"] = target
    write_meta(ticket_id, meta)


def _cmd_check(args: argparse.Namespace) -> int:
    cur = current_phase(args.ticket)
    if can_enter(cur, args.target):
        print(f"OK {cur} -> {args.target}")
        return 0
    allowed = sorted(TRANSITIONS.get(cur, set())) or ["(none)"]
    print(f"DENIED {cur} -> {args.target}; allowed: {allowed}")
    return 1


def _cmd_advance(args: argparse.Namespace) -> int:
    advance(args.ticket, args.target, note=args.note or "")
    print(f"ADVANCED {args.ticket} -> {args.target}")
    return 0


def _cmd_back(args: argparse.Namespace) -> int:
    back(args.ticket, args.target, reason=args.reason)
    print(f"BACK {args.ticket} -> {args.target}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    print(current_phase(args.ticket))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="dry-run a transition")
    p.add_argument("--ticket", required=True)
    p.add_argument("--target", required=True)
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("advance", help="move forward (legal transitions only)")
    p.add_argument("--ticket", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--note", default=None)
    p.set_defaults(func=_cmd_advance)

    p = sub.add_parser("back", help="rework — move backward with an audit entry")
    p.add_argument("--ticket", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=_cmd_back)

    p = sub.add_parser("show", help="print current phase")
    p.add_argument("--ticket", required=True)
    p.set_defaults(func=_cmd_show)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
