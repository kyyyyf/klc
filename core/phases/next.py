#!/usr/bin/env python3
"""`klc next <ticket>` — advance the ticket by one step.

- From `<X>:ack` → next phase's `:work` state, renders its prompt card.
- From `<X>:ack-needed` → ERROR pointing at `klc ack`.
- From `<X>:work` → ERROR pointing at `klc ack` (when done) or
  `klc abort` (to cancel).
- From `archived` → ERROR: terminal.

Always takes the per-ticket lock so concurrent `next`/`ack` can't race.
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
    ap = argparse.ArgumentParser(prog="klc next", description=__doc__)
    ap.add_argument("ticket")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        return _friendly_missing_ticket(args.ticket)

    try:
        with acquire_lock(args.ticket):
            cur = _lc.current_state(args.ticket)
            if cur == _ph.STATE_ARCHIVED:
                sys.stderr.write(
                    f"klc next: ticket {args.ticket} is archived; no next step.\n"
                )
                return 1

            pid, state = _ph.parse_state(cur)
            if state == _ph.STATE_WORK:
                sys.stderr.write(
                    f"klc next: ticket is in `{cur}`. Finish the work and run "
                    f"`klc ack {args.ticket}` (see required pick, if any), "
                    f"or `klc abort {args.ticket}` to cancel.\n"
                )
                return 1
            if state == _ph.STATE_ACK_NEEDED:
                ph = _ph.load_phases().by_id(pid)
                if ph.pick_required:
                    opts = ", ".join(f"{pk.id}={pk.label}" for pk in ph.picks)
                    sys.stderr.write(
                        f"klc next: ticket is in `{cur}`; run "
                        f"`klc ack {args.ticket} --pick N` (options: {opts}).\n"
                    )
                else:
                    sys.stderr.write(
                        f"klc next: ticket is in `{cur}`; run "
                        f"`klc ack {args.ticket}` to confirm.\n"
                    )
                return 1

            # state == :ack — advance.
            new_state = _lc.advance_to_next(args.ticket, note="klc next")
            meta = _lc.read_meta(args.ticket)
            if new_state == _ph.STATE_ARCHIVED:
                print(f"ARCHIVED {args.ticket}")
                return 0

            new_pid, _ = _ph.parse_state(new_state)
            card = write_prompt_card(args.ticket, new_pid, meta)
            print(f"→ {new_state}")
            print(f"  cat {card}")
            print(f"    # paste into your agent, then run `klc ack {args.ticket}`")
            return 0

    except LockedError as e:
        sys.stderr.write(f"klc next: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"klc next: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
