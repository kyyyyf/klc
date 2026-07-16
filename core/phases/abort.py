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
import socket
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import identity  # noqa: E402
import holder  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
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

    # KLC-061 (AC-3): abort mutates shared tracked state (supersede + budgets +
    # set_state back to prev :ack), so feature-ON it runs inside state_tx —
    # self-heal → pull → body → glob-commit + CAS-push, with deferred Jira (AC-4).
    # abort leaves a held `<X>:work`, so it RELEASES that phase's holder in the
    # same body (mirroring ack). Feature-OFF, state_tx is a no-op and no holder is
    # written (AC-5).
    aborted: dict = {}
    try:
        with acquire_lock(args.ticket):
            with state_tx.state_tx(args.ticket, f"abort {args.ticket}") as tx:
                aborted["new_state"] = _lc.abort(args.ticket)
                if tx is not None:
                    ident = {"id": identity.current(),
                             "machine": socket.gethostname()}
                    holder.release_holder(args.ticket, ident)
            new_state = aborted["new_state"]
            print(f"ABORTED → {new_state}")
            print(f"  current phase artefacts moved to _superseded/")
            print(f"  budgets reset; `klc jump <phase> {args.ticket}` is now legal")
            return 0
    except state_sync.StaleStateError:
        sys.stderr.write(
            f"klc abort: remote state advanced since you started — "
            f"re-run `klc abort {args.ticket}`.\n"
        )
        return 1
    except state_sync.StashConflictError:
        sys.stderr.write(
            "klc abort: local changes conflict with the remote — resolve "
            "manually; your work is saved in the git stash.\n"
        )
        return 1
    except state_sync.StateConflictError:
        sys.stderr.write(
            "klc abort: concurrent update — another writer moved this "
            "ticket; retry.\n"
        )
        return 1
    except holder.HolderConflictError as e:
        # HolderConflictError subclasses RuntimeError → must precede the catch-all.
        hid = e.holder.get("id") if e.holder else "?"
        sys.stderr.write(f"klc abort: phase held by {hid}\n")
        return 1
    except (state_sync.RetryExhaustedError,
            state_sync.RebaseConflictError,
            state_sync.ConfigError,
            RuntimeError):
        sys.stderr.write("klc abort: state sync failed — retry.\n")
        return 1
    except LockedError as e:
        sys.stderr.write(f"klc abort: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"klc abort: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
