#!/usr/bin/env python3
"""`klc ack <ticket> [--pick N]` — confirm work and move on.

Only valid from `<X>:ack-needed`. The state machine (phases.yml)
decides what `--pick` values are allowed and where each one leads
(usually `next`, sometimes a jump back into `<phase>:work` with
supersede). This script has no phase-specific knowledge.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
from artefacts import acquire_lock, write_prompt_card, LockedError  # noqa: E402
import phase_completion  # noqa: E402
import scope_delta as _sd  # noqa: E402

# Phases where expansion (scope creep) blocks ack toward next.
_SCOPE_GUARD_PHASES = {"review", "integrate"}


def _friendly_missing_ticket(ticket: str) -> int:
    sys.stderr.write(
        f"klc: unknown ticket {ticket!r}; run `klc intake {ticket}` "
        f"or `klc board` to list live tickets\n"
    )
    return 1


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc ack", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("--pick", type=int, default=None,
                    help="numeric pick id (see `klc status <ticket>` for options)")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        return _friendly_missing_ticket(args.ticket)

    try:
        with acquire_lock(args.ticket):
            cur = _lc.current_state(args.ticket)
            if cur == _ph.STATE_ARCHIVED:
                sys.stderr.write(
                    f"klc ack: ticket {args.ticket} is archived.\n"
                )
                return 1

            pid, state = _ph.parse_state(cur)
            if state == _ph.STATE_WORK:
                # KLC-02: Check for manual completion artifacts
                can_complete, error = phase_completion.can_complete(args.ticket, pid)
                if can_complete:
                    # Artifacts complete — auto-advance to ack-needed
                    sys.stderr.write(
                        f"klc ack: detected manual completion for {pid} phase\n"
                    )
                    new_state = _ph.STATE_ACK_NEEDED
                    _lc.set_state(
                        args.ticket,
                        pid,
                        new_state,
                        event="manual-completion",
                        note="artifacts detected by phase_completion.py"
                    )
                    sys.stderr.write(f"→ {pid}:{new_state} (manual completion)\n")
                    # Recurse: now in ack-needed, apply normal ack logic
                    return run(argv)
                else:
                    # Artifacts incomplete — show specific error
                    sys.stderr.write(
                        f"klc ack: ticket is in `{cur}`; cannot complete:\n"
                        f"  {error}\n"
                        f"(or `klc abort {args.ticket}` to cancel).\n"
                    )
                    return 1
            if state == _ph.STATE_ACK:
                sys.stderr.write(
                    f"klc ack: ticket is already in `{cur}`; run "
                    f"`klc next {args.ticket}` to advance.\n"
                )
                return 1

            # Scope-expansion guard before approving review / integrate.
            if pid in _SCOPE_GUARD_PHASES:
                delta = _sd.compare(args.ticket)
                if delta.get("expansion") and not delta.get("skipped"):
                    # Write a conflict note into review-report.md if it exists.
                    _write_scope_conflict(args.ticket, pid, delta)
                    sys.stderr.write(
                        f"klc ack: scope expansion detected — unplanned modules "
                        f"touched: {delta['expansion']}\n"
                        f"  planned={delta['planned']}\n"
                        f"  actual={delta['actual']}\n"
                        f"Update meta.json:affected_modules or use `klc jump` "
                        f"to restart review with the correct scope.\n"
                    )
                    return 1
                if delta.get("drift") and not delta.get("skipped"):
                    sys.stderr.write(
                        f"klc ack: scope drift warning — modules not in plan: "
                        f"{delta['drift']}\n"
                    )

            new_state = _lc.apply_ack(args.ticket, args.pick)

            if new_state == _ph.STATE_ARCHIVED:
                print(f"ARCHIVED {args.ticket}")
                return 0

            # Render prompt card for the new :work phase (if any).
            new_pid, new_st = _ph.parse_state(new_state)
            if new_st == _ph.STATE_WORK:
                meta = _lc.read_meta(args.ticket)
                step = 1 if new_pid == "build" else None
                card = write_prompt_card(args.ticket, new_pid, meta, step=step)
                print(f"→ {new_state}")
                print(f"  cat {card}")
                if new_pid == "build":
                    print(f"    # paste into your agent; use `klc step {args.ticket} N` for subsequent steps")
                else:
                    print(f"    # paste into your agent, then run `klc ack {args.ticket}`")
            else:
                print(f"→ {new_state}")
            return 0

    except LockedError as e:
        sys.stderr.write(f"klc ack: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"klc ack: {e}\n")
        return 1


def _write_scope_conflict(ticket: str, phase_id: str, delta: dict) -> None:
    """Append a [!CONFLICT] entry to the review report when scope expands."""
    from _paths import klc_ticket_dir
    report_name = "review-report.md" if phase_id == "review" else f"{phase_id}.md"
    report = klc_ticket_dir(ticket) / report_name
    conflict = (
        f"\n\n---\n"
        f"[!CONFLICT] scope-expansion detected at {phase_id}:ack-needed\n"
        f"  planned modules: {delta['planned']}\n"
        f"  actual modules:  {delta['actual']}\n"
        f"  unplanned:       {delta['expansion']}\n"
        f"Resolve: update meta.json:affected_modules to include all touched "
        f"modules, then re-run `klc ack {ticket}`.\n"
    )
    try:
        with open(report, "a", encoding="utf-8") as fh:
            fh.write(conflict)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
