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
import json
import socket
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
from artefacts import acquire_lock, write_prompt_card, LockedError  # noqa: E402
import identity  # noqa: E402
import holder  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402


class _StaleStateError(Exception):
    """Raised inside the tx when the pull advanced the remote phase past the one
    validated pre-tx — refuse to advance from stale state."""


def _friendly_missing_ticket(ticket: str) -> int:
    sys.stderr.write(
        f"klc: unknown ticket {ticket!r}; run `klc intake {ticket}` "
        f"or `klc board` to list live tickets\n"
    )
    return 1


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc next", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
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

            # state == :ack — advance INSIDE state_tx, AFTER the pull, so
            # `pull_rebase` sees a clean tree and the advance is captured in the
            # rollback snapshot. The entered phase is first-grabbed in the SAME
            # body so one CAS push carries both (AC-6a); a phase already held by
            # ANOTHER user raises HolderConflictError — report it, do NOT steal
            # (stealing is KLC-058) — and the tx rolls the advance back.
            # MED-1: archiving also runs the tx (so the archived phase + released
            # holder reach the remote), it just SKIPS acquire (no phase to hold).
            # Feature-off, state_tx is a no-op and no holder is written (AC-8b).
            advanced: dict = {}
            try:
                with state_tx.state_tx(
                    args.ticket, f"next {args.ticket}"
                ) as tx:
                    # Uniform post-pull revalidation (mirrors ack): if the pull
                    # advanced the remote phase past the `:ack` we validated
                    # pre-tx, refuse rather than advance from stale state.
                    if tx is not None and _lc.current_state(args.ticket) != cur:
                        raise _StaleStateError()
                    new_state = _lc.advance_to_next(args.ticket, note="klc next")
                    advanced["new_state"] = new_state
                    if tx is not None:
                        ident = {"id": identity.current(),
                                 "machine": socket.gethostname()}
                        if new_state == _ph.STATE_ARCHIVED:
                            holder.release_holder(args.ticket, ident)
                        else:
                            holder.acquire_holder(args.ticket, ident)
            except _StaleStateError:
                sys.stderr.write(
                    "klc next: remote state advanced since you started — "
                    f"re-run `klc next {args.ticket}`.\n"
                )
                return 1
            except holder.HolderConflictError as e:
                hid = e.holder.get("id") if e.holder else "?"
                if advanced.get("new_state") == _ph.STATE_ARCHIVED:
                    # LOW-2: the archive branch RELEASES the holder — a conflict
                    # here means someone else still holds it, so word it for a
                    # release/archive rather than the acquire phrasing below.
                    sys.stderr.write(
                        f"klc next: cannot archive — phase still held by {hid}; "
                        f"they must release it first.\n"
                    )
                else:
                    sys.stderr.write(f"klc next: phase held by {hid}\n")
                return 1
            except state_sync.StateConflictError:
                sys.stderr.write(
                    "klc next: concurrent update — another writer moved this "
                    "ticket; retry.\n"
                )
                return 1
            except (state_sync.RetryExhaustedError,
                    state_sync.RebaseConflictError,
                    state_sync.ConfigError,
                    RuntimeError):
                # Terminal, non-CAS sync failure (RRC set above, plus a plain
                # RuntimeError — network/auth/protected-branch/NothingToCommit).
                # Clean message, no git internals (AC-7). The push did not land.
                sys.stderr.write(
                    "klc next: state sync failed — retry.\n"
                )
                return 1
            except ValueError:
                # advance_to_next raises ValueError for an illegal transition (a
                # user error) — surface it via the outer handler. A ValueError
                # AFTER the advance came from the push (bad path) → sync error.
                if "new_state" not in advanced:
                    raise
                sys.stderr.write("klc next: state sync failed — retry.\n")
                return 1
            new_state = advanced["new_state"]

            meta = _lc.read_meta(args.ticket)
            if new_state == _ph.STATE_ARCHIVED:
                if args.json:
                    print(json.dumps({"ticket": args.ticket, "phase": "archived",
                                      "track": meta.get("track")}))
                else:
                    print(f"ARCHIVED {args.ticket}")
                return 0

            new_pid, _ = _ph.parse_state(new_state)
            if args.json:
                print(json.dumps({"ticket": args.ticket, "phase": new_state,
                                  "track": meta.get("track")}))
                return 0

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
        sys.stderr.write(f"klc next: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"klc next: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
