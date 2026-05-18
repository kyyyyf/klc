#!/usr/bin/env python3
"""`klc abort <ticket>` — cancel current :work, return to previous :ack.

Only valid from a `<X>:work` state. Moves current phase artefacts to
`_superseded/<ts>/<phase>/`, resets budget counters, and drops back
to the previous phase's `:ack` (or `intake:ack-needed` if the current
phase is the first one).

Use abort when you realise the current :work is going nowhere — for
example, `build:work` step 3 is stuck, and you want to revisit the
design before continuing. After abort you're in an `:ack` state from
which `klc jump` is legal.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402


def _friendly_missing_ticket(ticket: str) -> int:
    sys.stderr.write(
        f"klc: unknown ticket {ticket!r}; run `klc intake {ticket}` "
        f"or `klc board` to list live tickets\n"
    )
    return 1


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc abort", description=__doc__)
    ap.add_argument("ticket")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        return _friendly_missing_ticket(args.ticket)

    try:
        with acquire_lock(args.ticket):
            new_state = _lc.abort(args.ticket)
            print(f"ABORTED → {new_state}")
            print(f"  current phase artefacts moved to _superseded/")
            print(f"  budgets reset; `klc jump <phase> {args.ticket}` is now legal")
            return 0
    except LockedError as e:
        sys.stderr.write(f"klc abort: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"klc abort: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
