#!/usr/bin/env python3
"""`klc steal <KEY>` — take over a ticket's holder slot when it is stale.

The `holder` sub-object in meta.json records who owns the ticket's active
phase (see KLC-056). A live agent keeps it fresh with `heartbeat_holder`
(KLC-058). If that agent dies or wanders off, the holder goes stale and the
ticket is stuck — nobody else can acquire it.

`klc steal` is the recovery path. It takes over the holder slot ONLY when the
current holder's liveness timestamp (heartbeat_at, else since) is OLDER than
the staleness TTL (default 30 min). Within the TTL it refuses — the holder is
assumed alive. On a legitimate takeover it prints a warning naming the
displaced holder before overwriting the slot with the caller's identity.

    klc steal KLC-058
    klc steal KLC-058 --ttl-minutes 5   # tighter staleness window
"""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import holder  # noqa: E402
import identity as _identity  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402


def _friendly_missing_ticket(ticket: str) -> int:
    sys.stderr.write(
        f"klc: unknown ticket {ticket!r}; run `klc intake {ticket}` "
        f"or `klc board` to list live tickets\n"
    )
    return 1


def _resolve_identity() -> dict:
    """Build the holder identity dict the stealer will claim.

    holder._validate_identity requires BOTH `id` and `machine`, but
    identity.current() (KLC-055) only yields the `id` string. Pair it with the
    local hostname so the constructed dict satisfies the holder contract.
    """
    return {"id": _identity.current(), "machine": socket.gethostname()}


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc steal", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument(
        "--ttl-minutes", type=float, default=None,
        help="staleness window in minutes before a holder is stealable "
             "(default: 30)",
    )
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        return _friendly_missing_ticket(args.ticket)

    ttl_seconds = (args.ttl_minutes * 60 if args.ttl_minutes is not None
                   else holder.HOLDER_TTL_SECONDS)

    identity = _resolve_identity()

    def _warn_before_takeover(prev: dict, age: float) -> None:
        sys.stderr.write(
            f"WARNING: {args.ticket} holder {prev.get('id')!r} is stale "
            f"(idle {int(age)}s ≥ TTL {int(ttl_seconds)}s); taking over.\n"
        )

    try:
        with acquire_lock(args.ticket):
            result = holder.steal_holder(
                args.ticket, identity,
                ttl_seconds=ttl_seconds,
                on_takeover=_warn_before_takeover,
            )
    except holder.HolderActiveError as e:
        sys.stderr.write(f"klc steal: {e}\n")
        return 1
    except (ValueError, holder.HolderConflictError) as e:
        sys.stderr.write(f"klc steal: {e}\n")
        return 1
    except LockedError as e:
        sys.stderr.write(f"klc steal: {e}\n")
        return 1

    prev = result["previous"]
    new = result["holder"]
    print(
        f"STOLEN {args.ticket} → {new['id']} "
        f"(was {prev.get('id')}, idle {int(result['age_seconds'])}s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
