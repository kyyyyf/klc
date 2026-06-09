#!/usr/bin/env python3
"""`klc jira` — Jira integration commands.

Subcommands:
    klc jira status <KEY>               read-only: show klc phase vs Jira status
    klc jira sync <KEY> [--dry-run]     report mismatch + add/update artefact links
    klc jira sync <KEY> --apply         apply artefact links + update meta.jira_sync
    klc jira reconcile <KEY> push       push klc phase to Jira (explicit; managed mode)

Push/pull state changes are in KLC-021/022. This file (KLC-020) is the
read-only and enrich part only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))

from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402


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
    import jira_sync as _js
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

    try:
        import jira_sync as _js
        result = _js.pull(key, to_phase,
                          force=force,
                          reason=reason or None)
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
