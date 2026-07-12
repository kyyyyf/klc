#!/usr/bin/env python3
"""`klc state init [<remote>]` — materialize the project's state branch.

KLC stores per-ticket lifecycle artifacts under `.klc/` (see `.klc/tickets/...`).
Rather than keeping that state in a separate repository, KLC keeps it on an
**orphan branch** named `klc-state` inside the *same* project repo — its history
is disjoint from `main`, so state commits never pollute the code history and vice
versa.

`klc state init` is a one-time-per-checkout operation that materializes that
`klc-state` branch as a git **worktree** mounted at `.klc/`:

  * If `klc-state` already exists (on the remote or locally) the worktree is
    added tracking it, preserving any `.klc/tickets/...` files already present in
    the checkout.
  * If `klc-state` does not exist anywhere it is created as an orphan branch with
    an empty root commit, and the `.klc/` worktree is bound to it.
  * A second run is idempotent: if `.klc/` is already a registered worktree the
    command is a no-op and exits 0.

The command operates on the git repo containing the current working directory.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

STATE_BRANCH = "klc-state"
STATE_DIR = ".klc"
DEFAULT_REMOTE = "origin"
_BACKUP_DIR = STATE_DIR + ".init-bak"


def _git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


def _is_git_repo(repo: Path) -> bool:
    return _git(["rev-parse", "--git-dir"], repo, check=False).returncode == 0


def _is_klc_worktree(repo: Path) -> bool:
    """True if `.klc` is already a registered git worktree of this repo."""
    target = (repo / STATE_DIR).resolve()
    out = _git(["worktree", "list", "--porcelain"], repo, check=False).stdout
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):]).resolve()
            if path == target:
                return True
    return False


def _stash_existing(klc: Path, repo: Path):
    """Move any pre-existing `.klc/` content aside so `git worktree add` (which
    refuses a non-empty target) can proceed.  Returns the backup dir or None."""
    if not klc.exists():
        return None
    if not any(klc.iterdir()):
        # Empty directory: `git worktree add` would refuse it; just remove it.
        klc.rmdir()
        return None
    backup = repo / _BACKUP_DIR
    if backup.exists():
        shutil.rmtree(backup)
    klc.rename(backup)
    return backup


def _remote_has_state(repo: Path, remote: str) -> bool:
    """True if `<remote>` advertises a klc-state head."""
    out = _git(["ls-remote", "--heads", remote, STATE_BRANCH], repo, check=False)
    return out.returncode == 0 and bool(out.stdout.strip())


def _local_has_state(repo: Path) -> bool:
    """True if a local klc-state branch ref already exists."""
    r = _git(["show-ref", "--verify", "--quiet", f"refs/heads/{STATE_BRANCH}"], repo, check=False)
    return r.returncode == 0


def _add_worktree(repo: Path, klc: Path, remote: str) -> None:
    """Materialize the `.klc` worktree, selecting the right source for
    klc-state: an existing local branch, an existing remote branch (tracked),
    or a freshly created orphan branch."""
    if _local_has_state(repo):
        _git(["worktree", "add", str(klc), STATE_BRANCH], repo)
    elif _remote_has_state(repo, remote):
        _git(["fetch", remote, STATE_BRANCH], repo, check=False)
        _git(
            ["worktree", "add", "--track", "-b", STATE_BRANCH,
             str(klc), f"{remote}/{STATE_BRANCH}"],
            repo,
        )
    else:
        # No klc-state anywhere → create it as an orphan with an empty root
        # commit (so the ref exists and history is disjoint from main).
        _git(["worktree", "add", "--orphan", "-b", STATE_BRANCH, str(klc)], repo)
        _git(["commit", "--allow-empty", "-m", "klc-state: initialize orphan root"], klc)


def _restore_on_failure(backup, klc: Path) -> None:
    if backup is not None and not klc.exists():
        backup.rename(klc)


def _merge_back(backup, klc: Path) -> None:
    """Copy preserved content back into the worktree (local files win)."""
    if backup is None:
        return
    for item in backup.iterdir():
        dest = klc / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)
    shutil.rmtree(backup)


def run(argv: list[str]) -> int:
    args = list(argv)
    if not args or args[0] != "init":
        sys.stderr.write("usage: klc state init [<remote>]\n")
        return 2

    remote = args[1] if len(args) > 1 else DEFAULT_REMOTE

    repo = Path.cwd()
    if not _is_git_repo(repo):
        sys.stderr.write("klc state init: not inside a git repository\n")
        return 1

    klc = repo / STATE_DIR

    # Idempotent: already materialized.
    if _is_klc_worktree(repo):
        print(f"klc state: {STATE_DIR}/ already initialized (worktree present); nothing to do.")
        return 0

    backup = _stash_existing(klc, repo)
    try:
        _add_worktree(repo, klc, remote)
    except subprocess.CalledProcessError as e:
        _restore_on_failure(backup, klc)
        sys.stderr.write(f"klc state init: git error: {e.stderr or e}\n")
        return 1

    _merge_back(backup, klc)
    print(f"klc state: initialized {STATE_DIR}/ worktree on branch {STATE_BRANCH}.")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
