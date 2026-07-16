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

_SKILLS = Path(__file__).resolve().parent.parent / "skills"
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))
import state_sync  # noqa: E402  — single source of truth for the derived-ignore set

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


def _ensure_remote_tracks_state(repo: Path, remote: str) -> None:
    """Ensure `remote.<remote>.fetch` maps klc-state into a remote-tracking ref.

    A single-branch clone's fetch refspec covers only its one branch, so git
    refuses to set up tracking against `<remote>/klc-state` ("not a branch")
    even once the ref exists. Adding the branch to the remote's fetch config
    makes `<remote>/klc-state` a first-class remote-tracking branch so
    `worktree add --track` works. Idempotent: a no-op when already covered
    (e.g. the default `+refs/heads/*:refs/remotes/<remote>/*` wildcard)."""
    fetch_cfg = _git(
        ["config", "--get-all", f"remote.{remote}.fetch"], repo, check=False
    ).stdout
    src_full = "refs/heads/*"
    src_exact = f"refs/heads/{STATE_BRANCH}"
    dst_full = f"refs/remotes/{remote}/*"
    dst_exact = f"refs/remotes/{remote}/{STATE_BRANCH}"
    covered = False
    for line in fetch_cfg.splitlines():
        spec = line.strip()
        if not spec:
            continue
        if spec.startswith("+"):
            spec = spec[1:]
        src, _, dst = spec.partition(":")
        # Only genuinely covered when the SOURCE side actually includes
        # refs/heads/klc-state (the full heads namespace or the exact branch)
        # AND the destination lands at refs/remotes/<remote>/klc-state. A
        # sub-namespace source like `refs/heads/release/*` writing to
        # `refs/remotes/<remote>/*` does NOT fetch klc-state, so it must not
        # count as covered.
        if src in (src_full, src_exact) and dst in (dst_full, dst_exact):
            covered = True
            break
    if not covered:
        _git(["remote", "set-branches", "--add", remote, STATE_BRANCH], repo, check=False)


def _set_state_upstream(repo: Path, remote: str) -> None:
    """Bind klc-state's upstream explicitly to `<remote>/klc-state`.

    `worktree add --track` derives `branch.klc-state.merge` by reverse-mapping
    the remote-tracking ref through the fetch refspecs and picks the first match
    — so a pre-existing sub-namespace wildcard (e.g.
    `+refs/heads/release/*:refs/remotes/<remote>/*`) can bind it to the wrong
    ref (`refs/heads/release/klc-state`), breaking `git pull` in `.klc/`. Set
    the config directly so the upstream is always correct."""
    _git(["config", f"branch.{STATE_BRANCH}.remote", remote], repo, check=False)
    _git(["config", f"branch.{STATE_BRANCH}.merge", f"refs/heads/{STATE_BRANCH}"],
         repo, check=False)


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
        # Remote confirmed the branch; refresh and track it. Make the remote
        # track klc-state, then fetch with an explicit refspec so
        # refs/remotes/<remote>/klc-state is updated to the freshly-fetched tip.
        # A bare `git fetch <remote> klc-state` only writes FETCH_HEAD, so in a
        # single-branch clone (whose configured refspec covers only its one
        # branch) the remote-tracking ref would be missing or stale — making the
        # following `worktree add` fail or bind to an old commit while reporting
        # success.
        _ensure_remote_tracks_state(repo, remote)
        # Force (`+`) so the tracking ref is overwritten to the current tip: if
        # klc-state was force-pushed / deleted+recreated (history rewritten), a
        # non-forced update is rejected as non-fast-forward and we'd otherwise
        # bind the worktree to the STALE ref. Check the result too — never
        # initialize from a possibly-stale ref after a failed fetch. The source
        # is fully qualified as `refs/heads/klc-state`: an unqualified source
        # would DWIM to a same-named *tag* (refs/tags/ is preferred), letting a
        # tag hijack the tracking ref that `_remote_state_status` verified as a
        # branch.
        fetched = _git(
            ["fetch", remote,
             f"+refs/heads/{STATE_BRANCH}:refs/remotes/{remote}/{STATE_BRANCH}"],
            repo, check=False,
        )
        if fetched.returncode != 0:
            raise StateInitError(
                f"failed to fetch {STATE_BRANCH} from {remote!r} "
                f"(git fetch exited {fetched.returncode}): "
                f"{fetched.stderr.strip() or '<no output>'}. Refusing to "
                f"initialize from a possibly-stale {remote}/{STATE_BRANCH}."
            )
        _git(
            ["worktree", "add", "--track", "-b", STATE_BRANCH,
             str(klc), f"{remote}/{STATE_BRANCH}"],
            repo,
        )
        _set_state_upstream(repo, remote)
        return

    if has_tracking:
        # We couldn't confirm via ls-remote (or it's momentarily gone), but a
        # local remote-tracking ref exists — track it rather than fork a new
        # orphan onto a disjoint branch.
        _ensure_remote_tracks_state(repo, remote)
        _git(
            ["worktree", "add", "--track", "-b", STATE_BRANCH,
             str(klc), f"{remote}/{STATE_BRANCH}"],
            repo,
        )
        _set_state_upstream(repo, remote)
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
    # Publish the freshly-created branch so state_sync (054) — which requires
    # @{upstream} — can drive it. Only if a remote is configured; pure local /
    # single-user use is valid with no upstream.
    if _remote_is_configured(repo, remote):
        # Branch-qualify BOTH sides of the push refspec: a bare `klc-state`
        # source is rejected ("src refspec klc-state matches more than one")
        # when a same-named tag exists, which would otherwise leave no remote
        # branch and no upstream on a reachable remote.
        push_refspec = f"refs/heads/{STATE_BRANCH}:refs/heads/{STATE_BRANCH}"
        pushed = _git(["push", "-u", remote, push_refspec], klc, check=False)
        if pushed.returncode != 0:
            # Local init succeeded; don't strand the user on a push failure
            # (offline / auth / permission). Warn and continue (exit 0).
            detail = pushed.stderr.strip() or "push failed"
            sys.stderr.write(
                f"klc state: warning: {STATE_BRANCH} created locally but not "
                f"pushed to {remote!r} ({detail}); run "
                f"`git -C {STATE_DIR} push -u {remote} {push_refspec}` when online "
                f"to enable multi-user sync.\n"
            )
        else:
            # Converge with the `present` path's tail: `push -u` writes
            # branch.*.{remote,merge}, but on a single-branch (or custom-refspec)
            # clone the fetch refspec still covers only the cloned branch, so
            # refs/remotes/<remote>/klc-state is never materialized and
            # `@{upstream}` fails ("not stored as a remote-tracking branch").
            # Add the fetch refspec, materialize the tracking ref, and bind the
            # upstream explicitly so state_sync can operate everywhere.
            _ensure_remote_tracks_state(repo, remote)
            _git(
                ["fetch", remote,
                 f"+refs/heads/{STATE_BRANCH}:refs/remotes/{remote}/{STATE_BRANCH}"],
                repo, check=False,
            )
            _set_state_upstream(repo, remote)


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
    # Guard `backup.exists()`: on any post-merge-back failure the backup is the
    # only pristine copy, but it must never raise if it is already gone (e.g. a
    # failure after the success-path cleanup) — restore is best-effort and must
    # not turn a handled failure into an unhandled FileNotFoundError (KLC-063).
    if backup is not None and backup.exists() and not klc.exists():
        backup.rename(klc)


def _merge_tree(src: Path, dst: Path, *, skip: frozenset = frozenset()) -> None:
    """Recursively copy `src` into `dst`, local (src) content winning.

    Preserves symlinks as symlinks (never dereferences, tolerates dangling
    links) and resolves dir-vs-file type clashes in favor of the local tree so
    the merge can never abort after the worktree already exists.

    `skip` names entries to ignore *at this level only* (not recursively) — used
    to skip a top-level `.git` in preserved content, which is either the old
    nested repo's metadata or a checkout's gitdir pointer and must never
    overwrite the `.git` file that `git worktree add` created for `.klc/`.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in skip:
            continue
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
    """Copy preserved content back into the worktree (local files win).

    The top-level `.git` in the preserved content is skipped so it can never
    clobber the worktree's `.git` pointer (which would make git inside `.klc/`
    talk to the old nested repo instead of this repo's klc-state worktree).

    The backup is NOT deleted here: it is the ONLY pristine copy of the user's
    preserved tickets and must survive until `_commit_preserved` has durably
    committed them (KLC-063 data-loss fix). `run()` drops the backup only on a
    fully successful init, and `_restore_backup` renames it back on any failure.
    """
    if backup is None:
        return
    _merge_tree(backup, klc, skip=frozenset({".git"}))


def _commit_preserved(repo: Path, klc: Path, remote: str) -> None:
    """Commit tickets merged back into the worktree onto `klc-state` and push them
    (KLC-063).

    `_add_worktree` commits/pushes the `klc-state` branch BEFORE `_merge_back`
    copies any pre-existing `.klc/tickets/...` into the worktree, so without this
    step the preserved files stay uncommitted and never reach a second clone —
    and a later remote creation of the same paths can make future pulls diverge.
    This commits them onto `klc-state` and (when a remote is configured) pushes,
    so the preserved state is durable and propagates.

    Fail-safe: makes NO empty commit when there is nothing to preserve (or the
    merge produced no tracked change). The caller keeps the pristine backup until
    this returns successfully, so a commit failure restores the preserved tickets
    (KLC-063 data-loss fix) rather than destroying them.

    Derived/local artifacts must NOT reach the shared klc-state branch (INV7):
    the derived index, per-ticket `.lock`, prompt cards, `.index.json` and
    `scratch/` are DERIVED from per-ticket meta and are process-/clone-local.
    NEW derived files are kept out of the commit via `git add` EXCLUDE PATHSPECS
    built from the `state_sync` derived set (single source of truth). This
    deliberately does NOT touch `info/exclude`: that file lives in the COMMON git
    dir and is shared by every worktree of the repo, so appending to it would
    silently hide unrelated files in the user's main worktree — a surprising side
    effect of a plain `klc state init`.

    ALREADY-TRACKED derived files (a legacy klc-state that committed them before
    the derived-ignore era) are then converged OUT with `git rm --cached`: the
    exclude alone would leave a tracked derived file modified-but-unstaged (dirty
    tree) and still on the shared branch. Untracking (keeping the file on disk)
    stages its removal so the preserved commit drops it and the worktree ends
    clean w.r.t. tracked files. This mirrors the runtime staging discipline in
    `state_sync.commit_and_push_cas_subtree` (exclude NEW + untrack TRACKED), so
    the derived-never-shared invariant is closed for init the same way.
    """
    _git(["add", "-A", "--", ".", *state_sync.derived_add_exclude_pathspecs()], klc)
    _git(["rm", "-r", "--cached", "-q", "--ignore-unmatch", "--",
          *state_sync.derived_untrack_pathspecs()], klc)
    # Nothing staged → no preserved content, or the merged files are identical to
    # what klc-state already carries. Do not create an empty commit; leave init's
    # output/exit code exactly as they were on the no-preserve path.
    if _git(["diff", "--cached", "--quiet"], klc, check=False).returncode == 0:
        return
    _git(["-c", "user.name=klc", "-c", "user.email=klc@localhost",
          "commit", "-m", "klc-state: preserve pre-existing tickets"], klc)
    if _remote_is_configured(repo, remote):
        # Fail-safe like the orphan-create push tail (see below): the preserved
        # tickets are already committed locally, so a push failure (offline /
        # auth / permission) must NOT tear init down — warn and continue (exit 0).
        push_refspec = f"refs/heads/{STATE_BRANCH}:refs/heads/{STATE_BRANCH}"
        pushed = _git(["push", remote, push_refspec], klc, check=False)
        if pushed.returncode != 0:
            detail = pushed.stderr.strip() or "push failed"
            sys.stderr.write(
                f"klc state: warning: preserved tickets committed to "
                f"{STATE_BRANCH} locally but not pushed to {remote!r} ({detail}); "
                f"run `git -C {STATE_DIR} push {remote} {push_refspec}` when "
                f"online so other clones receive them.\n"
            )


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

    # Drop stale worktree registrations whose directory no longer exists, so a
    # removed-but-unpruned `.klc/` cannot masquerade as an initialized worktree
    # and yield a false idempotent success (it stays in `worktree list` until
    # pruned).
    _git(["worktree", "prune"], repo, check=False)

    # Idempotency is gated on a *fully completed* prior init: a registered
    # worktree checked out on klc-state AND no leftover backup. A worktree on a
    # different branch, or a stranded `.klc.init-bak`, means the prior init did
    # not complete correctly, so we must not report success.
    klc_branch = _klc_worktree_branch(repo)
    if klc_branch is not None and not klc.exists():
        # Still registered but the directory is gone. The only worktree that
        # survives the earlier `prune` is a *locked* one, and git refuses to
        # remove a locked worktree with a single `--force` — it requires a
        # double force (`-f -f`). Use it so the stale registration is actually
        # dropped and we fall through to re-materialize rather than report a
        # false success.
        _git(["worktree", "remove", "--force", "--force", str(klc)], repo, check=False)
        _git(["worktree", "prune"], repo, check=False)
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
        _commit_preserved(repo, klc, remote)
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

    # Init fully succeeded: the preserved tickets are now committed on klc-state,
    # so the pristine backup is redundant. Drop it only here (never in
    # `_merge_back`) so a failure anywhere up to this point can always restore it
    # (KLC-063 data-loss fix). Do NOT silently ignore a cleanup failure: the init
    # already succeeded so it must not become a hard error, but a leftover backup
    # would make the NEXT init refuse as an "interrupted init", so surface it
    # clearly (leftover path) instead of hiding it.
    if backup is not None and backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError as e:
            sys.stderr.write(
                f"klc state: warning: init succeeded but the backup {backup} "
                f"could not be removed ({e}); remove it manually, otherwise the "
                f"next `klc state init` will refuse it as an interrupted init.\n"
            )

    print(f"klc state: initialized {STATE_DIR}/ worktree on branch {STATE_BRANCH}.")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
