#!/usr/bin/env python3
"""`klc jira-sync` — manage the Jira push queue.

Usage:
  klc jira-sync             drain the queue, verbose output
  klc jira-sync status      show queue size and oldest entry
  klc jira-sync --dry-run   show what would be sent, no network calls
  klc jira-sync --quiet     drain silently (used by pre-commit hook)
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))


def run(argv: list[str]) -> int:
    import jira_sync
    # map subcommand 'status' → cli 'status'; everything else → 'flush' with flags
    if argv and argv[0] == "status":
        return jira_sync._cli(["status"])
    return jira_sync._cli(["flush", *argv])


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
