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
  * A second run is idempotent: if `.klc/` is already a *fully materialized*
    worktree the command is a no-op and exits 0.

The command operates on the project repo, resolved from `PROJECT_ROOT` (if set)
or from `git rev-parse --show-toplevel`, so it works from any subdirectory.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

STATE_BRANCH = "klc-state"
STATE_DIR = ".klc"
DEFAULT_REMOTE = "origin"
_BACKUP_DIR = STATE_DIR + ".init-bak"

# `git worktree add --orphan` requires git >= 2.42.
_MIN_GIT_FOR_ORPHAN = (2, 42)


class StateInitError(Exception):
    """A recoverable, user-facing failure raised during initialization."""


def _git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


def _git_version(cwd: Path) -> tuple[int, ...]:
    out = _git(["--version"], cwd, check=False).stdout
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    if not m:
        return (0,)
    return tuple(int(p) for p in m.groups(default="0"))


def _resolve_repo() -> Path | None:
    """Resolve the project repo root.

    Honor `PROJECT_ROOT` like every other klc command; otherwise resolve the
    enclosing repo via `git rev-parse --show-toplevel` so running from a
    subdirectory still targets the repo-root `.klc/`.
    """
    env = os.environ.get("PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    r = _git(["rev-parse", "--show-toplevel"], Path.cwd(), check=False)
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip()).resolve()
    return None


def _is_git_repo(repo: Path) -> bool:
    return _git(["rev-parse", "--git-dir"], repo, check=False).returncode == 0


def _worktree_branches(repo: Path) -> dict:
    """Map each registered worktree's resolved path -> its checked-out branch
    short-name ('' when the worktree is in detached-HEAD state)."""
    out = _git(["worktree", "list", "--porcelain"], repo, check=False).stdout
    info: dict = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = Path(line[len("worktree "):]).resolve()
            info[cur] = ""  # unknown/detached until a branch line proves otherwise
        elif cur is not None and line.startswith("branch "):
            ref = line[len("branch "):].strip()
            if ref.startswith("refs/heads/"):
                ref = ref[len("refs/heads/"):]
            info[cur] = ref
        elif cur is not None and line.strip() == "detached":
            info[cur] = ""
    return info


def _klc_worktree_branch(repo: Path) -> str | None:
    """Return the branch checked out in the `.klc` worktree, or None if `.klc`
    is not a registered worktree. '' means the worktree is detached."""
    return _worktree_branches(repo).get((repo / STATE_DIR).resolve())


def _is_klc_worktree(repo: Path) -> bool:
    """True if `.klc` is already a registered git worktree of this repo."""
    return (repo / STATE_DIR).resolve() in _worktree_branches(repo)


def _stash_existing(klc: Path, repo: Path):
    """Move any pre-existing `.klc/` content aside so `git worktree add` (which
    refuses a non-empty target) can proceed.  Returns the backup dir or None.

    Refuses to clobber an existing backup: a leftover `.klc.init-bak` may be the
    only surviving copy of tickets from an earlier interrupted run.
    """
    if not klc.exists():
        return None
    if not any(klc.iterdir()):
        # Empty directory: `git worktree add` would refuse it; just remove it.
        klc.rmdir()
        return None
    backup = repo / _BACKUP_DIR
    if backup.exists():
        raise StateInitError(
            f"{_BACKUP_DIR}/ already exists — a previous `klc state init` was "
            f"interrupted and left ticket data there. Resolve it manually "
            f"(merge or remove {_BACKUP_DIR}/) before re-running."
        )
    klc.rename(backup)
    return backup


def _remote_is_configured(repo: Path, remote: str) -> bool:
    """True if `<remote>` is a configured git remote of this repo."""
    r = _git(["config", "--get", f"remote.{remote}.url"], repo, check=False)
    return r.returncode == 0 and bool(r.stdout.strip())


def _remote_state_status(repo: Path, remote: str) -> str:
    """Probe `<remote>` for a klc-state head, distinguishing a verified answer
    from a lookup failure.

    Returns one of:
      * "present"     — remote advertises refs/heads/klc-state
      * "absent"      — no such remote, or remote reachable and verifiably has
                        no such branch (nothing to fork from → safe to orphan)
      * "unreachable" — remote *is* configured but ls-remote failed (offline /
                        auth / remote down); the branch's existence is *unknown*,
                        NOT confirmed absent, so we must not orphan blindly.
    """
    if not _remote_is_configured(repo, remote):
        return "absent"
    out = _git(["ls-remote", "--heads", remote, STATE_BRANCH], repo, check=False)
    if out.returncode != 0:
        return "unreachable"
    return "present" if out.stdout.strip() else "absent"


def _has_remote_tracking_ref(repo: Path, remote: str) -> bool:
    """True if a local `refs/remotes/<remote>/klc-state` tracking ref resolves
    (works offline; lets us materialize even when the remote is unreachable)."""
    r = _git(
        ["rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{STATE_BRANCH}"],
        repo, check=False,
    )
    return r.returncode == 0


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
        return

    status = _remote_state_status(repo, remote)
    has_tracking = _has_remote_tracking_ref(repo, remote)

    if status == "present":
        # Remote confirmed the branch; refresh and track it.
        _git(["fetch", remote, STATE_BRANCH], repo, check=False)
        _git(
            ["worktree", "add", "--track", "-b", STATE_BRANCH,
             str(klc), f"{remote}/{STATE_BRANCH}"],
            repo,
        )
        return

    if has_tracking:
        # We couldn't confirm via ls-remote (or it's momentarily gone), but a
        # local remote-tracking ref exists — track it rather than fork a new
        # orphan onto a disjoint branch.
        _git(
            ["worktree", "add", "--track", "-b", STATE_BRANCH,
             str(klc), f"{remote}/{STATE_BRANCH}"],
            repo,
        )
        return

    if status == "unreachable":
        # Existence is unknown and we have no local ref to fall back on. Do NOT
        # silently create an orphan that could fork state away from the remote.
        raise StateInitError(
            f"cannot reach remote {remote!r} to check for the {STATE_BRANCH} "
            f"branch (offline / expired credentials / remote unavailable), and no "
            f"local {remote}/{STATE_BRANCH} tracking ref exists. Refusing to "
            f"create a fresh orphan branch that could fork state. Restore "
            f"connectivity (or fetch {remote}/{STATE_BRANCH}) and re-run."
        )

    # status == "absent" and no tracking ref → the branch is verifiably missing
    # everywhere → create it as an orphan with an empty root commit (so the ref
    # exists and history is disjoint from main).
    ver = _git_version(repo)
    if ver < _MIN_GIT_FOR_ORPHAN:
        need = ".".join(str(p) for p in _MIN_GIT_FOR_ORPHAN)
        have = ".".join(str(p) for p in ver)
        raise StateInitError(
            f"git >= {need} is required to create the {STATE_BRANCH} orphan "
            f"branch ('git worktree add --orphan'); found git {have}. "
            f"Please upgrade git."
        )
    _git(["worktree", "add", "--orphan", "-b", STATE_BRANCH, str(klc)], repo)
    # Pass identity inline so the root commit succeeds even on a repo with
    # no configured user.name/user.email (fresh clone, CI, containers).
    _git(
        ["-c", "user.name=klc", "-c", "user.email=klc@localhost",
         "commit", "--allow-empty", "-m", "klc-state: initialize orphan root"],
        klc,
    )


def _teardown_partial(repo: Path, klc: Path, *, stashed: bool) -> None:
    """Remove a half-created `.klc` worktree so the backup can be restored and
    no stranded partial worktree is left behind.

    `stashed` says whether the user's original `.klc` was moved aside to the
    backup dir. The blind `rmtree` fallback (for the rare case `git worktree
    remove` declines) only fires when `stashed` is true — otherwise whatever is
    at `.klc` is the user's untouched original, which must never be deleted.
    """
    if _is_klc_worktree(repo) or klc.exists():
        _git(["worktree", "remove", "--force", str(klc)], repo, check=False)
    _git(["worktree", "prune"], repo, check=False)
    if stashed and klc.exists():
        # `worktree remove` declined; the partial content is disposable
        # (the user's real data lives in the backup dir).
        shutil.rmtree(klc, ignore_errors=True)


def _restore_backup(backup, klc: Path) -> None:
    if backup is not None and not klc.exists():
        backup.rename(klc)


def _merge_tree(src: Path, dst: Path) -> None:
    """Recursively copy `src` into `dst`, local (src) content winning.

    Preserves symlinks as symlinks (never dereferences, tolerates dangling
    links) and resolves dir-vs-file type clashes in favor of the local tree so
    the merge can never abort after the worktree already exists.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        # Local (src) content always wins. A symlink at the destination must be
        # removed outright, never followed: `is_dir()`/`exists()` dereference a
        # symlink, so a symlink-to-directory would otherwise be recursed *into*
        # — writing preserved tickets outside `.klc/`. Unlinking first also
        # guarantees the subsequent type checks see the real entry, if any.
        if target.is_symlink():
            target.unlink()
        if item.is_symlink():
            if target.is_dir():
                shutil.rmtree(target)  # local symlink replaces a colliding dir
            elif target.exists():
                target.unlink()
            os.symlink(os.readlink(item), target)
        elif item.is_dir():
            if target.exists() and not target.is_dir():
                target.unlink()  # local dir replaces a colliding file
            _merge_tree(item, target)
        else:  # regular file
            if target.is_dir():
                shutil.rmtree(target)  # local file replaces a colliding dir
            elif target.exists():
                target.unlink()
            shutil.copy2(item, target, follow_symlinks=False)


def _merge_back(backup, klc: Path) -> None:
    """Copy preserved content back into the worktree (local files win)."""
    if backup is None:
        return
    _merge_tree(backup, klc)
    shutil.rmtree(backup)


def run(argv: list[str]) -> int:
    args = list(argv)
    if not args or args[0] != "init":
        sys.stderr.write("usage: klc state init [<remote>]\n")
        return 2

    remote = args[1] if len(args) > 1 else DEFAULT_REMOTE

    repo = _resolve_repo()
    if repo is None or not _is_git_repo(repo):
        sys.stderr.write("klc state init: not inside a git repository\n")
        return 1

    klc = repo / STATE_DIR
    backup_dir = repo / _BACKUP_DIR

    # Idempotency is gated on a *fully completed* prior init: a registered
    # worktree checked out on klc-state AND no leftover backup. A worktree on a
    # different branch, or a stranded `.klc.init-bak`, means the prior init did
    # not complete correctly, so we must not report success.
    klc_branch = _klc_worktree_branch(repo)
    if klc_branch is not None:
        if klc_branch != STATE_BRANCH:
            where = f"branch {klc_branch!r}" if klc_branch else "a detached HEAD"
            sys.stderr.write(
                f"klc state init: {STATE_DIR}/ is already a git worktree checked "
                f"out on {where}, not {STATE_BRANCH!r}. Remove or re-point that "
                f"worktree (git worktree remove {STATE_DIR}) before re-running.\n"
            )
            return 1
        if backup_dir.exists():
            sys.stderr.write(
                f"klc state init: {STATE_DIR}/ worktree is present but "
                f"{_BACKUP_DIR}/ still exists — a previous init did not complete. "
                f"Resolve {_BACKUP_DIR}/ manually before re-running.\n"
            )
            return 1
        print(f"klc state: {STATE_DIR}/ already initialized (worktree present); nothing to do.")
        return 0

    # No worktree yet, but a stranded backup means an earlier run was
    # interrupted; refuse rather than risk destroying its data.
    if backup_dir.exists():
        sys.stderr.write(
            f"klc state init: {_BACKUP_DIR}/ exists from an interrupted previous "
            f"init but {STATE_DIR}/ is not a worktree. Resolve {_BACKUP_DIR}/ "
            f"manually before re-running.\n"
        )
        return 1

    backup = None
    try:
        backup = _stash_existing(klc, repo)
        _add_worktree(repo, klc, remote)
        _merge_back(backup, klc)
    except (subprocess.CalledProcessError, StateInitError, OSError) as e:
        # Tear down any partial worktree first, THEN restore the backup, so
        # ticket data is never stranded and the next run starts clean. This
        # covers git failures, our own StateInitError, AND filesystem errors
        # (OSError) raised during add-worktree/merge-back — a merge-back that
        # hits an unreadable file or a failed copy must still restore the backup.
        _teardown_partial(repo, klc, stashed=backup is not None)
        _restore_backup(backup, klc)
        detail = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
        sys.stderr.write(f"klc state init: {detail or e}\n")
        return 1

    print(f"klc state: initialized {STATE_DIR}/ worktree on branch {STATE_BRANCH}.")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
