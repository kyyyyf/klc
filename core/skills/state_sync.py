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


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )


def commit_and_push_cas(
    paths,
    msg: str,
    ticket: str,
    klc_dir: Path,
    remote: str = "origin",
    max_retries: int = 3,
) -> None:
    """Stage *paths*, commit *msg*, and push HEAD to *remote* with CAS semantics.

    On a non-fast-forward rejection the remote commits are inspected:

    * If any remote commit touches ``tickets/<ticket>/`` the push is a
      single-writer violation and :class:`StateConflictError` is raised
      immediately (no retry).
    * Otherwise the remote change is absorbed via rebase and the push is
      retried, up to *max_retries* times, after which
      :class:`RetryExhaustedError` is raised.

    Raises :class:`ValueError` (before any git operation) if a path does not
    exist, and :class:`ConfigError` if *klc_dir* has no configured upstream.
    """
    klc_dir = Path(klc_dir)

    # Validate all paths BEFORE touching git.
    for p in paths:
        if not (klc_dir / p).exists():
            raise ValueError(f"path does not exist: {p}")

    # Require a configured upstream for the current branch.
    up = _git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        klc_dir,
    )
    if up.returncode != 0:
        raise ConfigError(
            f"no upstream configured for current branch in {klc_dir}"
        )

    # Stage + commit (list args only; msg is a single non-shell argument).
    _git(["add", "--", *[str(p) for p in paths]], klc_dir)
    commit = _git(["commit", "-m", msg], klc_dir)
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.strip() or commit.stdout.strip())

    prefix = f"tickets/{ticket}/"
    attempt = 0
    while True:
        push = _git(["push", remote, "HEAD"], klc_dir)
        if push.returncode == 0:
            return

        err = push.stderr or ""
        if "non-fast-forward" not in err and "rejected" not in err:
            raise RuntimeError(err.strip() or push.stdout.strip())

        # Absorb the remote tip and classify the conflict.
        _git(["fetch", remote], klc_dir)
        changed = _git(
            ["log", "--name-only", "--format=", "HEAD..@{upstream}"], klc_dir
        )
        touched = [ln.strip() for ln in changed.stdout.splitlines() if ln.strip()]
        if any(f.startswith(prefix) for f in touched):
            raise StateConflictError(
                f"same-ticket single-writer violation on {ticket}: "
                f"remote touched {[f for f in touched if f.startswith(prefix)]}"
            )

        if attempt >= max_retries:
            raise RetryExhaustedError(
                f"push rejected after {max_retries} retr"
                f"{'y' if max_retries == 1 else 'ies'} on {ticket}"
            )

        rebase = _git(["rebase", "@{upstream}"], klc_dir)
        if rebase.returncode != 0:
            _git(["rebase", "--abort"], klc_dir)
            raise RebaseConflictError(rebase.stderr.strip())
        attempt += 1
