#!/usr/bin/env python3
"""`klc ship <ticket> [--pick N]` — ack + next in one atomic step.

Equivalent to running `klc ack <ticket> [--pick N]` followed immediately
by `klc next <ticket>`, but under a single lock so no concurrent command
can interleave between the two transitions.

Valid from `<X>:ack-needed`. Errors on:
  - `<X>:work`     — finish the work first, then ship
  - `<X>:ack`      — already acked; just run `klc next`
  - `archived`     — terminal state

If the phase requires a pick and --pick is omitted, prints the available
options and exits 1 without modifying any state.
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
    ap = argparse.ArgumentParser(prog="klc ship", description=__doc__)
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
                    f"klc ship: ticket {args.ticket} is archived.\n"
                )
                return 1

            pid, state = _ph.parse_state(cur)

            if state == _ph.STATE_WORK:
                sys.stderr.write(
                    f"klc ship: ticket is in `{cur}`; finish the work first "
                    f"(or `klc abort {args.ticket}` to cancel).\n"
                )
                return 1

            if state == _ph.STATE_ACK:
                sys.stderr.write(
                    f"klc ship: ticket is already in `{cur}`; "
                    f"run `klc next {args.ticket}` to advance.\n"
                )
                return 1

            # state == :ack-needed — validate pick before touching state
            ph = _ph.load_phases().by_id(pid)
            if ph.pick_required and args.pick is None:
                opts = ", ".join(f"{pk.id}={pk.label}" for pk in ph.picks)
                sys.stderr.write(
                    f"klc ship: `{cur}` requires a pick; "
                    f"re-run with --pick N (options: {opts}).\n"
                )
                return 1

            # Step 1: ack
            after_ack = _lc.apply_ack(args.ticket, args.pick)

            if after_ack == _ph.STATE_ARCHIVED:
                print(f"ARCHIVED {args.ticket}")
                return 0

            # Step 2: advance from :ack to next :work
            new_state = _lc.advance_to_next(args.ticket, note="klc ship")
            meta = _lc.read_meta(args.ticket)

            if new_state == _ph.STATE_ARCHIVED:
                print(f"ARCHIVED {args.ticket}")
                return 0

            new_pid, _ = _ph.parse_state(new_state)
            step = 1 if new_pid == "build" else None
            card = write_prompt_card(args.ticket, new_pid, meta, step=step)
            print(f"→ {new_state}")
            print(f"  cat {card}")
            if new_pid == "build":
                print(f"    # paste into your agent; use `klc step {args.ticket} N` for subsequent steps")
            else:
                print(f"    # paste into your agent, then run `klc ack {args.ticket}`")
            return 0

    except LockedError as e:
        sys.stderr.write(f"klc ship: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"klc ship: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
