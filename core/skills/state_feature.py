"""state_feature — the single authoritative multi-user on/off switch (KLC-057).

`enabled()` is the one detector consulted by `state_tx` (and, transitively, by
`intake` / `ack` / `next`) to decide whether the serverless multi-user machinery
(`state_sync` pull/CAS-push + `holder` lifecycle) runs at all.

It returns True iff BOTH hold for the project's `.klc/` directory:

  1. `.klc/` is a git worktree whose checked-out branch is `klc-state` — the
     orphan branch materialized by `klc state init` (KLC-053). There is no
     remote *named* klc-state; detection is the worktree's HEAD branch.
  2. That branch has a configured upstream (`@{upstream}` resolves).

Both are required. `state_sync.pull_rebase` / `commit_and_push_cas` hard-require
`@{upstream}`; a no-remote single-user `klc-state` orphan has none, so the
feature must read OFF there and behave exactly as today rather than crash the
verbs. Any git error — or a missing upstream — yields False (fail-safe OFF).
"""
from __future__ import annotations

import subprocess

from _paths import klc_dir


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(klc_dir()),
        capture_output=True,
        text=True,
        timeout=5,
    )


def enabled() -> bool:
    """True iff `.klc/` is a klc-state worktree WITH a configured upstream."""
    try:
        head = _git(["symbolic-ref", "--short", "HEAD"])
        if head.returncode != 0 or head.stdout.strip() != "klc-state":
            return False
        up = _git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
        )
        return up.returncode == 0 and bool(up.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False
