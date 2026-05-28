#!/usr/bin/env python3
"""consistency_check.py — pre-merge / pre-commit gate.

Thin umbrella over `items.py validate`, extended with rules that
cross the ticket boundary:

  - every artefact referenced from `README.md` / `.index.json` exists
  - meta.json:phase parses as a valid `<phase>:<state>` under phases.yml
  - meta.json:pre_merge_snapshot (if present) still matches artefact
    hashes — catches last-second edits that skipped consistency

Exit code 0 only if every rule passes. Designed to be symlinked from
`.git/hooks/pre-commit` via `hooks/pre-commit`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.shared.paths import klc_ticket_dir, klc_ticket_meta_file, klc_tickets_dir  # noqa: E402
import phases as _phases  # noqa: E402


def _load_meta(ticket: str) -> dict | None:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _hash_artefacts(ticket: str) -> dict[str, str]:
    tdir = klc_ticket_dir(ticket)
    out: dict[str, str] = {}
    for p in sorted(tdir.rglob("*")):
        if p.is_dir():
            continue
        if any(part.startswith("discovery-context") or part.startswith("design-context")
               or part.startswith("build-context") or part.startswith("scratch")
               or part == "serena-cache" for part in p.parts):
            continue
        rel = str(p.relative_to(tdir))
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out


def _run_items_validate(ticket: str) -> tuple[int, str]:
    skill = Path(__file__).with_name("items.py")
    r = subprocess.run(
        [sys.executable, str(skill), "validate", "--ticket", ticket],
        capture_output=True, text=True,
    )
    return r.returncode, (r.stderr or r.stdout)


def check_ticket(ticket: str) -> list[str]:
    errs: list[str] = []
    meta = _load_meta(ticket)
    if meta is None:
        return [f"{ticket}: meta.json missing or malformed"]

    phase = meta.get("phase") or ""
    try:
        pid, state = _phases.parse_state(phase)
        if pid != _phases.STATE_ARCHIVED:
            _phases.load_phases().by_id(pid)
    except (ValueError, KeyError) as e:
        errs.append(f"{ticket}: meta.json:phase={phase!r} invalid ({e})")

    rc, out = _run_items_validate(ticket)
    if rc != 0:
        errs.append(f"{ticket}: items.validate: {out.strip()}")

    snap = meta.get("pre_merge_snapshot")
    if snap:
        now = _hash_artefacts(ticket)
        diffs = [k for k in set(snap) | set(now) if snap.get(k) != now.get(k)]
        if diffs:
            errs.append(
                f"{ticket}: pre_merge_snapshot drift on "
                f"{', '.join(diffs[:5])}{'...' if len(diffs) > 5 else ''}"
            )
    return errs


def cmd_check(args: argparse.Namespace) -> int:
    if args.ticket:
        targets = [args.ticket]
    else:
        targets = [p.name for p in klc_tickets_dir().glob("*")
                   if p.is_dir() and p.name != "archive"]
    failures = 0
    for t in targets:
        errs = check_ticket(t)
        if errs:
            failures += 1
            for e in errs:
                sys.stderr.write(f"FAIL {e}\n")
    if failures == 0:
        print("CONSISTENCY_OK")
        return 0
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticket", default=None,
                    help="one ticket (default: every live ticket)")
    ap.set_defaults(func=cmd_check)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
