#!/usr/bin/env python3
"""`klc back <ticket> <phase> --reason "<why>" [--json]` — return to an earlier phase.

Works from `:work`, `:ack-needed` and `:ack`. Supersedes the outputs of the
phases from `<phase>` to the current one, moves to `<phase>:work`, records
`{from, to, reason, at, by}` in `meta.rework[]`, bumps `rework_count[<phase>]`
once, and renders the target card with a `## Rework request` section that quotes
the reason. A missing reason, a phase after the current one, and a terminal
ticket are refused (exit 2) before anything is written; so is an unknown
ticket. Unexpected errors (a locked or conflicting state) exit 1. Going back to
`build` also renders the step card (`build/_prompt_step_N.md`, N = the ticket's
current step, default 1) with the same `## Rework request` section, because that
is the card `klc go` and `klc status` point at.

`klc back <ticket> --cancel --reason "<why>"` is `klc abort --cancel`.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import epic_deps as _edeps  # noqa: E402
import identity  # noqa: E402
import holder  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
from artefacts import acquire_lock, render_card, LockedError  # noqa: E402


def _err(msg: str) -> None:
    sys.stderr.write(f"klc back: {msg}\n")


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc back", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("phase", nargs="?", default=None,
                    help="phase id to return to (at or before the current phase)")
    ap.add_argument("--reason", default=None,
                    help="why the work is sent back (REQUIRED)")
    ap.add_argument("--cancel", action="store_true",
                    help="cancel the ticket (the same cancel the deprecated abort verb performs)")
    ap.add_argument("--json", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0

    reason = (args.reason or "").strip()
    if not reason:
        _err('--reason "<why>" is required')
        return 2
    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(
            f"klc: unknown ticket {args.ticket!r}; run `klc intake {args.ticket}` "
            f"or `klc board` to list live tickets\n")
        return 2

    if args.cancel:
        import abort as _abort
        return _abort.run([args.ticket, "--cancel", "--reason", reason])

    if not args.phase:
        _err("a target phase is required (or --cancel)")
        return 2
    meta = _lc.read_meta(args.ticket)
    cur = meta.get("phase", "")
    if _ph.is_terminal(cur):
        _err(f"ticket is {cur}; a terminal ticket cannot go back")
        return 2
    if _ph.is_terminal(args.phase):
        _err(f"`{args.phase}` is a terminal state, not a phase")
        return 2
    try:  # refuse an unknown or forward target before any write
        _lc.jump(args.ticket, args.phase, dry_run=True, from_any=True)
    except ValueError as e:
        _err(str(e))
        return 2

    by = identity.current()
    done: dict = {}
    try:
        with acquire_lock(args.ticket):
            with state_tx.state_tx(args.ticket, f"back {args.ticket}") as tx:
                done["plan"] = _lc.jump(
                    args.ticket, args.phase, dry_run=False, from_any=True,
                    rework_entry={"reason": reason, "by": by})
                if tx is not None:
                    ident = {"id": by, "machine": socket.gethostname()}
                    holder.acquire_holder(args.ticket, ident)
                    holder.heartbeat_holder(args.ticket)
            plan = done["plan"]
            meta = _lc.read_meta(args.ticket)
            card = render_card(args.ticket, args.phase, meta).path
            if args.phase == "build":
                # the card go/status name is the step card; it carries the reason too
                card = render_card(args.ticket, "build", meta,
                                   step=meta.get("impl_step") or 1).path
            if args.json:
                print(json.dumps({"ticket": args.ticket, "from": plan["from"],
                                  "to": plan["to"], "reason": reason,
                                  "card": str(card)}))
                return 0
            print(f"→ {plan['to']}")
            print(f"  cat {card}")
            print(f"    # paste into your agent, then run `klc go {args.ticket}`")
            return 0
    except state_sync.StaleStateError:
        _err("remote state advanced since you started — re-run the command.")
        return 1
    except state_sync.StashConflictError:
        _err("local changes conflict with the remote — resolve manually; "
             "your work is saved in the git stash.")
        return 1
    except state_sync.StateConflictError:
        _err("concurrent update — another writer moved this ticket; retry.")
        return 1
    except holder.HolderConflictError as e:
        hid = e.holder.get("id") if e.holder else "?"
        _err(f"target phase held by {hid}")
        return 1
    except _edeps.BlockedError as be:
        _err(be.edge.message())
        return 1
    except (state_sync.RetryExhaustedError, state_sync.RebaseConflictError,
            state_sync.ConfigError, RuntimeError):
        _err("state sync failed — retry.")
        return 1
    except LockedError as e:
        _err(str(e))
        return 1
    except ValueError as e:
        _err(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
