#!/usr/bin/env python3
"""`klc jira` — Jira integration commands.

Subcommands:
    klc jira status <KEY>               read-only: show klc phase vs Jira status
    klc jira sync <KEY> [--dry-run]     report mismatch + add/update artefact links
    klc jira sync <KEY> --apply         apply artefact links + update meta.jira_sync
    klc jira reconcile <KEY> push       push klc phase to Jira (explicit; managed mode)
    klc jira reconcile <KEY> pull --to <phase>         move klc to match Jira
    klc jira reconcile <KEY> force-pull --to <phase> --reason ...

KLC-020 introduced the read-only/enrich subcommands; the state-changing
reconcile pull/force-pull (KLC-021/022) move the klc phase to match Jira.

KLC-061: `reconcile pull`/`force-pull` mutate shared tracked state
(`meta.phase` via lifecycle.jira_pull → set_state), so they now run inside
the per-ticket `acquire_lock` + `state_tx` envelope — a CAS-pushed pull with
holder authorization and deferred Jira, exactly like abort/jump/steal/ack/next.
`reconcile push` and `status` write only to the external Jira service (or
read), touch no klc tracked state, and are deliberately NOT wrapped.

KLC-065 (deferred from KLC-061 Q-002): `sync --apply` writes only
`meta.jira_sync` advisory drift bookkeeping. That is still tracked state under
`tickets/<key>/meta.json`, so feature-ON it now runs inside the same
`acquire_lock` + `state_tx` CAS-push envelope (at the `cmd_sync` call site) —
otherwise the write is stranded locally until a later verb pushes it. Because
it is NOT a phase/ownership move, it deliberately takes NO holder authorization
(unlike `reconcile pull`). Feature-OFF it is a byte-identical direct local
write, no lock and no git.
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
import identity  # noqa: E402
import holder  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
import state_feature  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402


def _load_config():
    """Load JiraConfig; return None if integration disabled."""
    try:
        from jira_config import load, JiraConfigError
        cfg = load()
        if not cfg.enabled:
            return None
        return cfg
    except Exception as exc:
        sys.stderr.write(f"klc jira: config error — {exc}\n")
        return None


def _jira_status(key: str, cfg) -> str | None:
    """Return current Jira status name for key, or None on error."""
    try:
        from jira_client import make_client
        client = make_client(cfg)
        issue = client.get_issue(key)
        return ((issue.get("fields") or {}).get("status") or {}).get("name")
    except RuntimeError as exc:
        sys.stderr.write(f"klc jira: {exc}\n")
        return None


def cmd_status(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc jira status",
                                 description="Show klc phase vs Jira status (read-only).")
    ap.add_argument("key", help="Ticket key (e.g. KLC-020)")
    args = ap.parse_args(argv)

    cfg = _load_config()
    if cfg is None:
        sys.stderr.write("klc jira: integration not enabled (set enabled: true in jira.yml)\n")
        return 1

    if not klc_ticket_meta_file(args.key).exists():
        sys.stderr.write(f"klc jira: unknown ticket {args.key!r}\n")
        return 1

    meta = _lc.read_meta(args.key)
    phase_full = meta.get("phase", "")
    # Extract phase id (strip :state)
    phase_id = phase_full.split(":")[0] if ":" in phase_full else phase_full

    jira_status = _jira_status(args.key, cfg)
    if jira_status is None:
        return 1

    expected_jira = cfg.klc_to_jira.get(phase_id)

    print(f"KLC phase:    {phase_full}")
    print(f"Jira status:  {jira_status}")
    if expected_jira and jira_status != expected_jira:
        print(f"MISMATCH: klc expects Jira to be {expected_jira!r}, got {jira_status!r}")
        print(f"  Run `klc jira sync {args.key} --apply` or `klc jira reconcile {args.key} push`")
        return 1

    print("OK: in sync")
    return 0


def cmd_sync(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc jira sync",
                                 description="Report mismatch + manage artefact links.")
    ap.add_argument("key", help="Ticket key")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be done, no writes")
    ap.add_argument("--apply", action="store_true",
                    help="Apply artefact links and update meta.jira_sync")
    args = ap.parse_args(argv)

    cfg = _load_config()
    if cfg is None:
        sys.stderr.write("klc jira: integration not enabled\n")
        return 1

    if not klc_ticket_meta_file(args.key).exists():
        sys.stderr.write(f"klc jira: unknown ticket {args.key!r}\n")
        return 1

    meta = _lc.read_meta(args.key)
    phase_full = meta.get("phase", "")
    phase_id = phase_full.split(":")[0] if ":" in phase_full else phase_full

    jira_status = _jira_status(args.key, cfg)
    if jira_status is None:
        return 1

    expected_jira = cfg.klc_to_jira.get(phase_id)
    mismatch = expected_jira and jira_status != expected_jira

    print(f"KLC phase:    {phase_full}")
    print(f"Jira status:  {jira_status}")
    if mismatch:
        print(f"MISMATCH: klc expects {expected_jira!r}")

    # Build artefact link plan
    from jira_artifacts import build_artifact_links
    link_body = build_artifact_links(args.key, cfg)
    print("\nArtefact links to upsert:")
    for line in link_body.splitlines():
        if line.startswith("- ["):
            print(f"  {line}")

    if args.dry_run or (not args.apply):
        print("\n(dry-run) No changes made. Pass --apply to write.")
        return 1 if mismatch else 0

    # Apply
    try:
        from jira_client import make_client
        from jira_artifacts import upsert_artifact_links
        client = make_client(cfg)
        upsert_artifact_links(client, args.key, args.key, cfg)
        print("Artefact links upserted.")
    except RuntimeError as exc:
        sys.stderr.write(f"klc jira: artefact link upsert failed — {exc}\n")
        return 1

    # Update meta.jira_sync; clear stale conflicts when Jira is now in sync.
    #
    # KLC-065 (deferred from KLC-061 Q-002): meta.jira_sync is advisory drift
    # bookkeeping (timestamps + last-seen status), NOT lifecycle/holder state. So
    # feature-ON it must still be committed + CAS-pushed within THIS verb — the
    # same acquire_lock → state_tx → write → CAS-push envelope KLC-061 gave the
    # reconcile-pull path — otherwise the write sits only in the local worktree
    # until a later verb pushes it and can be stranded in a stash on a rebase
    # conflict. But because it is NOT a phase/ownership move, we deliberately do
    # NOT acquire or check the holder (no acquire_holder / HolderConflictError):
    # any user or automation may reconcile drift without taking over the ticket.
    # We wrap ONLY here at the sync call site — the shared `_update_jira_sync_meta`
    # helper is also called by the `reconcile push` path (push_to_jira), which
    # stays unwrapped and byte-identical. Feature-OFF: state_feature.enabled() is
    # False → the direct local write with no lock and no git, byte-identical to
    # before this ticket. The Jira artefact-link upsert above is idempotent and is
    # intentionally left before/outside the tx (out of scope for advisory sync).
    import jira_sync as _js
    if state_feature.enabled():
        try:
            with acquire_lock(args.key):
                try:
                    with state_tx.state_tx(args.key, f"jira-sync {args.key}"):
                        _js._update_jira_sync_meta(
                            args.key, jira_status, phase_full, "sync",
                            clear_conflicts=not mismatch)
                except state_sync.NothingToCommitError:
                    # The write produced no tracked-state change (e.g. helper
                    # swallowed an internal error) → nothing to push; treat as a
                    # clean no-op and fall through to the normal return below.
                    pass
        except Exception as exc:
            # Any terminal tx failure — state_sync.* sync errors AND the plain
            # ValueError commit_and_push_cas_subtree raises when `git add -A` is
            # refused (corrupt index / disk-full / permission; state_sync.py:564),
            # which is NOT a RuntimeError subclass — must surface the friendly
            # message + return 1, never a raw traceback. state_tx has already
            # rolled the subtree back, so this is data-safe. Mirrors the terminal
            # `except Exception` in _reconcile_pull. (No HolderConflictError clause:
            # we never touch the holder — advisory bookkeeping, not an ownership
            # move.)
            sys.stderr.write(
                f"klc jira: jira_sync bookkeeping not pushed — {exc}\n")
            return 1
    else:
        _js._update_jira_sync_meta(args.key, jira_status, phase_full, "sync",
                                   clear_conflicts=not mismatch)
    print("meta.json:jira_sync updated.")
    return 1 if mismatch else 0


def cmd_reconcile(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc jira reconcile",
                                 description="Reconcile klc/Jira state divergence.")
    ap.add_argument("key", help="Ticket key")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("push", help="Push klc phase to Jira")
    p_pull = sub.add_parser("pull", help="Move klc to match Jira status")
    p_pull.add_argument("--to", required=True, dest="to_phase",
                        help="Target klc phase")
    p_fp = sub.add_parser("force-pull",
                           help="Move klc ignoring missing artefacts")
    p_fp.add_argument("--to", required=True, dest="to_phase",
                      help="Target klc phase")
    p_fp.add_argument("--reason", required=True,
                      help="Required: reason for skipping artefact checks (written to audit log)")
    args = ap.parse_args(argv)

    cfg = _load_config()
    if cfg is None:
        sys.stderr.write("klc jira: integration not enabled\n")
        return 1

    if args.action == "push":
        return _reconcile_push(args.key, cfg)

    if args.action == "pull":
        return _reconcile_pull(args.key, args.to_phase, force=False)

    if args.action == "force-pull":
        return _reconcile_pull(args.key, args.to_phase,
                               force=True, reason=args.reason)

    sys.stderr.write(f"klc jira reconcile: unknown action {args.action!r}\n")
    return 2


def _reconcile_pull(key: str, to_phase: str,
                    force: bool = False, reason: str = "") -> int:
    """Pull klc state to match Jira status."""
    if not klc_ticket_meta_file(key).exists():
        sys.stderr.write(f"klc jira: unknown ticket {key!r}\n")
        return 1

    # Determine direction BEFORE calling pull, so we can gate on TTY.
    import phases as _ph_mod
    import lifecycle as _lc_mod
    _is_backward = False
    try:
        meta_check = _lc_mod.read_meta(key)
        track_check = meta_check.get("track") or "M"
        ph_check = _ph_mod.load_phases()
        track_ids_check = [p.id for p in ph_check.track_phases(track_check)]
        cur_id = (meta_check.get("phase", "").split(":")[0]
                  if ":" in meta_check.get("phase", "") else meta_check.get("phase", ""))
        if cur_id in track_ids_check and to_phase in track_ids_check:
            _is_backward = track_ids_check.index(to_phase) < track_ids_check.index(cur_id)
    except Exception:
        pass

    # Backward (non-force) pull requires TTY confirmation — it supersedes artefacts.
    if _is_backward and not force:
        if not sys.stdin.isatty():
            sys.stderr.write(
                f"klc jira: backward pull (to {to_phase!r}) supersedes downstream "
                f"artefacts and requires interactive confirmation. "
                f"Run this command in a TTY, or use force-pull with --reason.\n"
            )
            return 1
        sys.stderr.write(
            f"[jira] Backward pull to {to_phase!r} will supersede downstream "
            f"artefacts. Continue? [y/N]: "
        )
        try:
            confirm = input().strip().lower()
        except EOFError:
            confirm = "n"
        if confirm != "y":
            sys.stderr.write("[jira] Pull cancelled.\n")
            return 1

    # KLC-061 (AC-3/AC-4): jira pull mutates shared tracked state (meta.phase via
    # lifecycle.jira_pull → set_state), so feature-ON it runs inside state_tx —
    # the phase move is CAS-pushed to origin and the Jira side-effect is deferred
    # until after the push (discarded on rollback). `_js.pull` never raises (it
    # returns a result dict), so a no-op / stopped / invalid pull mutates nothing;
    # the tx exit then has nothing to commit → NothingToCommitError, which we
    # treat as "clean, no change" and fall through to the normal result handling.
    # Feature-OFF, state_tx is a no-op and jira_pull fires Jira eagerly as before.
    #
    # NOTE (Q-002 → KLC-065): `klc jira sync --apply` writes only meta.jira_sync
    # drift bookkeeping. It is now wrapped in its OWN acquire_lock + state_tx at
    # the `cmd_sync` call site (durable CAS-push, no holder-auth), not here.
    # `reconcile push` and `jira status` touch no klc tracked state
    # (external/read-only) → no-op.
    try:
        import jira_sync as _js
        result: dict = {}
        # FIX-1(a): jira-pull now does git work (pull_rebase / commit / CAS-push)
        # inside state_tx, so it must hold the per-ticket lock that serializes
        # same-machine access to the shared `.klc` git repo — exactly like
        # abort/jump/steal/ack/next. Without it a concurrent lock-holding verb
        # (e.g. `klc ack`) would interleave git ops on the shared index.
        with acquire_lock(key):
            try:
                with state_tx.state_tx(key, f"jira-pull {key}") as tx:
                    result = _js.pull(
                        key, to_phase, force=force, reason=reason or None)
                    # FIX-1(b): jira-pull lands on `<target>:work` via set_state,
                    # the same shape as `jump`, so it ACQUIRES the target holder
                    # for the caller. acquire_holder raises HolderConflictError
                    # when the ticket is actively held by ANOTHER user — so a pull
                    # can never silently move someone else's held ticket — and it
                    # clears any stale holder carried across the phase change. Only
                    # on a REAL move (action == "pulled"): a no-op/stopped pull must
                    # not gratuitously claim the holder. Feature-OFF (tx is None):
                    # no holder write, byte-identical to before.
                    if (tx is not None and result.get("ok")
                            and result.get("action") == "pulled"):
                        ident = {"id": identity.current(),
                                 "machine": socket.gethostname()}
                        holder.acquire_holder(key, ident)
                        # P2: acquire_holder is idempotent for the SAME user and
                        # preserves the original `since`, so if the caller already
                        # held the ticket with a STALE holder the just-pulled phase
                        # would remain immediately stealable. Refresh liveness
                        # explicitly so the claimed phase is within TTL. Harmless
                        # for a freshly-acquired holder (heartbeat_at just tracks
                        # `since`); acquire_holder guarantees a holder exists here,
                        # so heartbeat_holder never hits its no-holder ValueError.
                        holder.heartbeat_holder(key)
            except state_sync.NothingToCommitError:
                # The pull made no tracked-state change (noop/stopped/invalid/
                # error); nothing to push. Use the captured result dict below.
                pass
    except state_sync.StaleStateError:
        sys.stderr.write(
            f"klc jira: remote state advanced since you started — re-run.\n")
        return 1
    except state_sync.StashConflictError:
        sys.stderr.write(
            "klc jira: local changes conflict with the remote — resolve "
            "manually; your work is saved in the git stash.\n")
        return 1
    except state_sync.StateConflictError:
        sys.stderr.write(
            "klc jira: concurrent update — another writer moved this ticket; "
            "retry.\n")
        return 1
    except holder.HolderConflictError as e:
        # Held by another user → refuse (no ownership bypass). HolderConflictError
        # and LockedError both subclass RuntimeError, so these clauses MUST precede
        # the RuntimeError catch-all below.
        hid = e.holder.get("id") if e.holder else "?"
        sys.stderr.write(f"klc jira: phase held by {hid}\n")
        return 1
    except LockedError as e:
        sys.stderr.write(f"klc jira: {e}\n")
        return 1
    except (state_sync.RetryExhaustedError,
            state_sync.RebaseConflictError,
            state_sync.ConfigError,
            RuntimeError):
        sys.stderr.write("klc jira: state sync failed — retry.\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"klc jira: pull failed — {exc}\n")
        return 1

    if result["ok"]:
        print(f"klc {key}: {result['detail']}")
        if result.get("skipped_phases"):
            print(f"  Skipped (condition): {result['skipped_phases']}")
        if result.get("missing_artifacts") and force:
            print(f"  Missing (force-skipped): {result['missing_artifacts']}")
        return 0
    elif result["action"] == "noop":
        print(f"Already at target. {result['detail']}")
        return 0
    elif result["action"] == "stopped":
        sys.stderr.write(f"klc jira: {result['detail']}\n")
        if result.get("skipped_phases"):
            print(f"  Skipped (condition, fine): {result['skipped_phases']}")
        if result.get("missing_artifacts"):
            print(f"  MISSING artefacts (blocking): {result['missing_artifacts']}")
            print(f"  Use `klc jira reconcile {key} force-pull --to {to_phase}"
                  f" --reason \"...\"` to proceed anyway.")
        return 1
    else:
        sys.stderr.write(f"klc jira: {result['detail']}\n")
        return 1


def _reconcile_push(key: str, cfg) -> int:
    """Push klc phase → Jira status. Delegates to jira_sync.push(key)."""
    if not klc_ticket_meta_file(key).exists():
        sys.stderr.write(f"klc jira: unknown ticket {key!r}\n")
        return 1

    try:
        import jira_sync as _js
        result = _js.push(key)
    except Exception as exc:
        sys.stderr.write(f"klc jira: push failed — {exc}\n")
        return 1

    if result["ok"]:
        print(f"Jira {key}: {result['detail']}")
        return 0
    elif result["action"] == "noop":
        print(f"Already in sync. {result['detail']}")
        return 0
    else:
        sys.stderr.write(f"klc jira: {result['detail']}\n")
        return 1


def run(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip())
        return 2

    sub = argv[0]
    rest = argv[1:]

    if sub == "status":
        return cmd_status(rest)
    if sub == "sync":
        return cmd_sync(rest)
    if sub == "reconcile":
        return cmd_reconcile(rest)

    sys.stderr.write(f"klc jira: unknown subcommand {sub!r}\n")
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
