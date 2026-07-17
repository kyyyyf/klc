#!/usr/bin/env python3
"""`klc steal <KEY>` — take over a ticket's holder slot when it is stale.

The `holder` sub-object in meta.json records who owns the ticket's active
phase (see KLC-056). A live agent keeps it fresh via `klc heartbeat` — the
throttled UserPromptSubmit hook that calls `heartbeat_holder` (KLC-058 provides
the primitive; KLC-064 provides this real caller). If that agent dies or wanders
off, the heartbeat stops, the holder goes stale, and the ticket is stuck —
nobody else can acquire it.

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
import state_sync  # noqa: E402
import state_tx  # noqa: E402
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

    # A TTL must be strictly positive. ttl<=0 would make the staleness gate
    # (age < ttl_seconds) reject nothing — every holder, however fresh, would
    # be stealable — defeating the "refuse while alive" data-safety contract.
    if args.ttl_minutes is not None and args.ttl_minutes <= 0:
        sys.stderr.write(
            f"klc steal: --ttl-minutes must be positive (got {args.ttl_minutes}); "
            f"a zero or negative TTL would steal a live holder\n"
        )
        return 1

    ttl_seconds = (args.ttl_minutes * 60 if args.ttl_minutes is not None
                   else holder.HOLDER_TTL_SECONDS)

    identity = _resolve_identity()

    def _warn_before_takeover(prev: dict, age: float) -> None:
        sys.stderr.write(
            f"WARNING: {args.ticket} holder {prev.get('id')!r} is stale "
            f"(idle {int(age)}s >= TTL {int(ttl_seconds)}s); taking over.\n"
        )

    # KLC-061 (AC-2): the holder mutation runs INSIDE state_tx so, feature-ON, it
    # is pull → mutate meta.holder → glob-commit + CAS-push — the steal is durable
    # on origin, not only in the caller's local worktree. The staleness check lives
    # inside holder.steal_holder, so it runs in the tx body AFTER the pull and never
    # judges staleness from stale local state. Note the envelope's stale-guard may
    # PREEMPT it: if the pull changed the ticket subtree at all (e.g. a peer
    # refreshed/advanced the holder), state_tx raises StaleStateError before the
    # body runs — the steal is refused with "remote state advanced" rather than
    # reaching the HolderActive check. Either way a live holder is never stolen.
    # Feature-OFF, state_tx is a no-op and steal_holder mutates local meta as before.
    result: dict = {}
    try:
        with acquire_lock(args.ticket):
            with state_tx.state_tx(args.ticket, f"steal {args.ticket}"):
                result = holder.steal_holder(
                    args.ticket, identity,
                    ttl_seconds=ttl_seconds,
                    on_takeover=_warn_before_takeover,
                )
    except holder.HolderActiveError as e:
        sys.stderr.write(f"klc steal: {e}\n")
        return 1
    except state_sync.StaleStateError:
        sys.stderr.write(
            f"klc steal: remote state advanced since you started — "
            f"re-run `klc steal {args.ticket}`.\n"
        )
        return 1
    except state_sync.StashConflictError:
        sys.stderr.write(
            "klc steal: local changes conflict with the remote — resolve "
            "manually; your work is saved in the git stash.\n"
        )
        return 1
    except state_sync.StateConflictError:
        sys.stderr.write(
            "klc steal: concurrent update — another writer moved this "
            "ticket; retry.\n"
        )
        return 1
    except (ValueError, holder.HolderConflictError) as e:
        # HolderConflictError subclasses RuntimeError, so this MUST precede the
        # RuntimeError catch-all below or a holder conflict would be masked as a
        # generic sync failure.
        sys.stderr.write(f"klc steal: {e}\n")
        return 1
    except (state_sync.RetryExhaustedError,
            state_sync.RebaseConflictError,
            state_sync.ConfigError,
            RuntimeError):
        sys.stderr.write("klc steal: state sync failed — retry.\n")
        return 1
    except LockedError as e:
        sys.stderr.write(f"klc steal: {e}\n")
        return 1

    prev = result["previous"]
    new = result["holder"]
    print(
        f"STOLEN {args.ticket} -> {new['id']} "
        f"(was {prev.get('id')}, idle {int(result['age_seconds'])}s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
