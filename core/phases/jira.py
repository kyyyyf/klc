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

    # Update meta.jira_sync
    _update_meta_jira_sync(args.key, meta, jira_status, phase_full, "sync")
    print("meta.json:jira_sync updated.")
    return 1 if mismatch else 0


def cmd_reconcile(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc jira reconcile",
                                 description="Reconcile klc/Jira state divergence.")
    ap.add_argument("key", help="Ticket key")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("push", help="Push klc phase to Jira")
    # pull and force-pull are KLC-022
    args = ap.parse_args(argv)

    cfg = _load_config()
    if cfg is None:
        sys.stderr.write("klc jira: integration not enabled\n")
        return 1

    if args.action == "push":
        return _reconcile_push(args.key, cfg)

    sys.stderr.write(f"klc jira reconcile: unknown action {args.action!r}\n")
    return 2


def _reconcile_push(key: str, cfg) -> int:
    """Push klc phase → Jira status. Single-hop; conflict on no direct transition."""
    if not klc_ticket_meta_file(key).exists():
        sys.stderr.write(f"klc jira: unknown ticket {key!r}\n")
        return 1

    meta = _lc.read_meta(key)
    phase_full = meta.get("phase", "")
    phase_id = phase_full.split(":")[0] if ":" in phase_full else phase_full

    target_status = cfg.klc_to_jira.get(phase_id)
    if not target_status:
        sys.stderr.write(
            f"klc jira reconcile push: no Jira status mapped for phase {phase_id!r}\n"
        )
        return 1

    try:
        from jira_client import make_client
        client = make_client(cfg)

        # Idempotency: check current status
        issue = client.get_issue(key)
        current = ((issue.get("fields") or {}).get("status") or {}).get("name")
        if current == target_status:
            print(f"Already at {target_status!r}. Nothing to do.")
            return 0

        # Find transition
        transitions = client.get_transitions(key)
        tid = None
        for t in transitions:
            name = (t.get("to") or {}).get("name") or t.get("name") or ""
            if name == target_status:
                tid = t["id"]
                break

        if tid is None:
            sys.stderr.write(
                f"klc jira: no direct transition to {target_status!r} from {current!r}.\n"
                f"  Available: {[((t.get('to') or {}).get('name') or t.get('name')) for t in transitions]}\n"
                f"  Move Jira to {target_status!r} manually, then run `klc jira sync {key} --apply`\n"
            )
            _write_conflict(key, meta, "transition-blocked",
                            f"No direct transition to {target_status!r} from {current!r}")
            return 1

        client.transition_issue(key, tid)
        # Add provenance comment
        client.add_comment(key, f"moved by klc — phase {phase_full}")
        print(f"Jira {key} → {target_status!r} ✓")

        _update_meta_jira_sync(key, meta, target_status, phase_full, "push")
        return 0

    except RuntimeError as exc:
        sys.stderr.write(f"klc jira: {exc}\n")
        return 1


def _update_meta_jira_sync(key: str, meta: dict, jira_status: str,
                             klc_phase: str, action: str) -> None:
    """Write meta.json:jira_sync block."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sync = meta.setdefault("jira_sync", {})
    sync.update({
        "enabled": True,
        "issue_key": key,
        "last_synced_at": now,
        "last_jira_status": jira_status,
        "last_klc_phase": klc_phase,
        "last_action": action,
    })
    sync.setdefault("conflicts", [])
    _lc.write_meta(key, meta)


def _write_conflict(key: str, meta: dict, conflict_type: str, detail: str) -> None:
    """Append a conflict entry to meta.json:jira_sync.conflicts."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sync = meta.setdefault("jira_sync", {})
    conflicts = sync.setdefault("conflicts", [])
    conflicts.append({
        "type": conflict_type,
        "detail": detail,
        "detected_at": now,
        "suggested": f"klc jira reconcile {key} push",
    })
    _lc.write_meta(key, meta)


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
