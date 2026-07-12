"""state_sync — git CAS coordination for the multi-user ``.klc/`` state.

The ``.klc/`` directory is a git worktree of the project's ``klc-state`` orphan
branch, pushed to ``origin``.  Multiple users may race to update it.  This
module provides:

* :func:`pull_rebase` — bring the local worktree up to date via
  ``git pull --rebase``.
* :func:`commit_and_push_cas` — a compare-and-swap style commit+push that
  rejects on a non-fast-forward and either transparently absorbs an
  *other-ticket* race (rebase + retry) or surfaces a *same-ticket*
  single-writer violation (:class:`StateConflictError`, no retry).

All git operations use list-argument subprocess calls (never ``shell=True``) to
guard against shell injection.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class StateConflictError(Exception):
    """Same-ticket CAS violation — another writer touched this ticket's state."""


class RebaseConflictError(Exception):
    """A merge conflict occurred while rebasing onto the remote."""


class RetryExhaustedError(Exception):
    """Max retries were hit while racing other-ticket writers."""


class ConfigError(Exception):
    """Required remote/upstream configuration is missing."""


def pull_rebase(klc_dir: Path) -> None:
    """Run ``git pull --rebase`` in *klc_dir*.

    Returns ``None`` on a clean rebase.  On failure the in-progress rebase is
    aborted and :class:`RebaseConflictError` is raised.
    """
    r = subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=str(klc_dir),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        subprocess.run(
            ["git", "rebase", "--abort"],
            cwd=str(klc_dir),
            capture_output=True,
        )
        raise RebaseConflictError(r.stderr.strip())
