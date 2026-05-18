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
                sys.stderr.write(
                    f"klc ack: ticket is in `{cur}`; finish the work first "
                    f"(or `klc abort {args.ticket}` to cancel).\n"
                )
                return 1
            if state == _ph.STATE_ACK:
                sys.stderr.write(
                    f"klc ack: ticket is already in `{cur}`; run "
                    f"`klc next {args.ticket}` to advance.\n"
                )
                return 1

            new_state = _lc.apply_ack(args.ticket, args.pick)

            if new_state == _ph.STATE_ARCHIVED:
                print(f"ARCHIVED {args.ticket}")
                return 0

            # Render prompt card for the new :work phase (if any).
            new_pid, new_st = _ph.parse_state(new_state)
            if new_st == _ph.STATE_WORK:
                meta = _lc.read_meta(args.ticket)
                card = write_prompt_card(args.ticket, new_pid, meta)
                print(f"→ {new_state}")
                print(f"  cat {card}")
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


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
