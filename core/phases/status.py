#!/usr/bin/env python3
"""`klc status <ticket>` — vertical path view of the ticket's progress.

Shows only the phases that apply to this track. Each row carries a
checkbox and, for the current phase, the exact sub-state:

  [✓] intake
  [✓] discovery
  [●] design            ← now · ack-needed (pick required: 1=A, 2=B, 3=C)
  [ ] detailed-test-plan
  [ ] build
  ...

The final line points the user at the next action.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_dir, klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import holder_display  # noqa: E402


BOX_DONE    = "[✓]"  # ✓
BOX_CURRENT = "[●]"  # ●
BOX_EMPTY   = "[ ]"


def _meta(ticket: str) -> dict | None:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        return None
    try:
        return _lc.read_meta(ticket)  # triggers legacy migration if needed
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

    if args.json:
        if phase_value == _ph.STATE_ARCHIVED:
            print(json.dumps({"ticket": args.ticket, "phase": "archived",
                              "track": track, "kind": kind,
                              "phase_id": "archived", "state": "archived"}))
            return 0
        try:
            cur_pid, cur_state = _ph.parse_state(phase_value)
        except ValueError:
            sys.stderr.write(
                f"klc status: meta.json:phase is unparseable: {phase_value!r}\n"
            )
            return 1
        print(json.dumps({"ticket": args.ticket, "phase": phase_value,
                          "track": track, "kind": kind,
                          "phase_id": cur_pid, "state": cur_state}))
        return 0

    print(f"{args.ticket}  track={track}  kind={kind}")
    print()

    if phase_value == _ph.STATE_ARCHIVED:
        ph = _ph.load_phases()
        for p in ph.track_phases(track):
            print(f"  {BOX_DONE} {p.id}")
        print(f"  {BOX_DONE} archived")
        return 0

    try:
        cur_pid, cur_state = _ph.parse_state(phase_value)
    except ValueError:
        sys.stderr.write(
            f"klc status: meta.json:phase is unparseable: {phase_value!r}\n"
        )
        return 1

    ph = _ph.load_phases()
    track_phases = ph.track_phases(track)
    phase_ids = [p.id for p in track_phases]
    try:
        cur_idx = phase_ids.index(cur_pid)
    except ValueError:
        sys.stderr.write(
            f"klc status: current phase {cur_pid!r} is not in track {track!r}. "
            f"Ticket may have been jumped off-track.\n"
        )
        cur_idx = -1

    # Render rows.
    for i, p in enumerate(track_phases):
        if i < cur_idx:
            print(f"  {BOX_DONE} {p.id}")
        elif i == cur_idx:
            annotation = _annotate_current(p, cur_state, meta)
            print(f"  {BOX_CURRENT} {p.id:<22} ← now · {annotation}")
        else:
            print(f"  {BOX_EMPTY} {p.id}")

    # Next-action hint.
    print()
    hint = _next_hint(args.ticket, cur_pid, cur_state, meta)
    print(hint)
    return 0


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
    tdir = klc_ticket_dir(ticket)
    if cur_state == _ph.STATE_WORK:
        card = tdir / cur_pid / "_prompt.md"
        if card.exists():
            rel = card.relative_to(tdir.parent.parent.parent) \
                if card.is_absolute() else card
            return (f"→ work in progress. Agent prompt: "
                    f"`cat {card}`\n"
                    f"  When done: `klc ack {ticket}` "
                    f"(with --pick if required), "
                    f"or `klc abort {ticket}` to cancel.")
        return (f"→ {cur_pid}:work. Run `klc ack {ticket}` when done, "
                f"or `klc abort {ticket}` to cancel.")
    if cur_state == _ph.STATE_ACK_NEEDED:
        ph = _ph.load_phases().by_id(cur_pid)
        if ph.pick_required:
            return f"→ run `klc ack {ticket} --pick N`"
        return f"→ run `klc ack {ticket}`"
    if cur_state == _ph.STATE_ACK:
        return f"→ run `klc next {ticket}` to advance"
    return ""


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
