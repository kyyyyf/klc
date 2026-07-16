#!/usr/bin/env python3
"""`klc ship <ticket> [--pick N]` — ack + next in one step.

Equivalent to running `klc ack <ticket> [--pick N]` followed immediately
by `klc next <ticket>`. Valid from `<X>:ack-needed`.

KLC-061: ship now DELEGATES to the already-wrapped verbs — it calls
`ack.run` (and, only if the ack leaves the ticket in an `:ack` state,
`next.run`) rather than calling `lifecycle.apply_ack` / `advance_to_next`
directly. This is required so that, feature-ON, the phase advance runs
inside a `state_tx` (self-heal → pull → CAS-push) with holder-auth and
deferred-Jira and reaches origin WITHIN this verb — instead of firing Jira
eagerly and never pushing (the pre-KLC-061 divergence bug).

For every current phase the forward pick's `goto` is `next`, so
`lifecycle.apply_ack` (inside `ack.run`) ALREADY advances to the next
phase's `:work`; the follow-up `next.run` is therefore only invoked in the
(currently unused) case where a pick leaves the ticket at `:ack`. So in
practice ship is a SINGLE atomic ack.run CAS push today; the second step is
a latent path kept for correctness.

Atomicity note (KLC-061 ADR D-002): ship does NOT hold a lock across the
delegated verbs — `acquire_lock` unlinks its lockfile on context exit and
is not re-entrant across a delegated `run()`. Each delegate manages its own
lock + state_tx, so ship is up to two independently-atomic CAS transactions;
an intermediate `<X>:ack` state is a valid, re-pullable resting point.

Errors on `<X>:work` (finish work first), `<X>:ack` (already acked; run
`klc next`), and `archived` (terminal). If a pick is required and omitted,
prints the options and exits 1 without modifying state.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
PHASES = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(PHASES))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
from artefacts import LockedError  # noqa: E402
import ack as _ack  # noqa: E402
import next as _next  # noqa: E402


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

    # Pre-flight guards (read-only, no lock — the delegated ack.run/next.run each
    # re-validate under their own lock + state_tx stale-guard). These preserve the
    # ship-branded errors and stop `:work`/`:ack` states from tripping ack.run's
    # manual-completion auto-advance.
    try:
        cur = _lc.current_state(args.ticket)
    except ValueError as e:
        sys.stderr.write(f"klc ship: {e}\n")
        return 1

    if cur == _ph.STATE_ARCHIVED:
        sys.stderr.write(f"klc ship: ticket {args.ticket} is archived.\n")
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

    # state == :ack-needed — validate pick before delegating.
    ph = _ph.load_phases().by_id(pid)
    if ph.pick_required and args.pick is None:
        opts = ", ".join(f"{pk.id}={pk.label}" for pk in ph.picks)
        sys.stderr.write(
            f"klc ship: `{cur}` requires a pick; "
            f"re-run with --pick N (options: {opts}).\n"
        )
        return 1

    try:
        # Step 1: ack — runs inside ack.run's state_tx (CAS-push + holder release
        # + deferred Jira). For every current pick (goto=next) apply_ack already
        # advances to the next phase's :work and ack.run renders the prompt card.
        ack_argv = [args.ticket]
        if args.pick is not None:
            ack_argv += ["--pick", str(args.pick)]
        rc = _ack.run(ack_argv)
        if rc != 0:
            return rc

        # ack.run already printed either `ARCHIVED` or the new :work prompt card.
        after = _lc.current_state(args.ticket)
        if after == _ph.STATE_ARCHIVED:
            return 0

        # Step 2: only if the ack left the ticket at an :ack state (no current
        # pick does — kept for correctness) advance further via next.run.
        _, after_state = _ph.parse_state(after)
        if after_state == _ph.STATE_ACK:
            return _next.run([args.ticket])
        return 0

    except LockedError as e:
        sys.stderr.write(f"klc ship: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"klc ship: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
