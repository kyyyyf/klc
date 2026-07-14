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
guard against shell injection, and run under a fixed ``C`` locale so stderr
parsing is stable regardless of the caller's environment.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Force a stable, English/C locale for every git invocation so that stderr
# classification (non-fast-forward detection, "nothing to commit", etc.) does
# not depend on the caller's locale.  ``GIT_TERMINAL_PROMPT=0`` prevents git
# from blocking on an interactive credential prompt.
_GIT_ENV = {
    **os.environ,
    "LC_ALL": "C",
    "LANG": "C",
    "GIT_TERMINAL_PROMPT": "0",
}

# Lower-cased stderr substrings that mark a genuine concurrent-write race on the
# pushed ref (a CAS conflict to absorb via fetch/rebase/retry).  A push rejected
# for any OTHER reason — protected branch, pre-receive/update hook decline, auth
# — matches none of these and is surfaced directly instead of being retried.
#   * "non-fast-forward" / "fetch first" — the remote already moved ahead.
#   * "cannot lock ref" / "failed to update ref" / "stale info" — the remote
#     advanced between ref advertisement and ref update (true simultaneous push).
_CAS_RACE_MARKERS = (
    "non-fast-forward",
    "fetch first",
    "cannot lock ref",
    "failed to update ref",
    "stale info",
)


class StateConflictError(Exception):
    """Same-ticket CAS violation — another writer touched this ticket's state."""


class RebaseConflictError(Exception):
    """A merge conflict occurred while rebasing onto the remote."""


class RetryExhaustedError(Exception):
    """Max retries were hit while racing other-ticket writers."""


class ConfigError(Exception):
    """Required remote/upstream configuration is missing."""


class NothingToCommitError(RuntimeError):
    """The supplied paths existed but had no staged changes to commit.

    Subclasses :class:`RuntimeError` so existing callers that catch the broad
    error continue to work, while new callers can distinguish the no-op case.
    """


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )


def _rebase_in_progress(cwd: Path) -> bool:
    """True if a rebase is currently in progress in *cwd*."""
    for name in ("rebase-merge", "rebase-apply"):
        gp = _git(["rev-parse", "--git-path", name], cwd)
        rel = gp.stdout.strip()
        if rel and (Path(cwd) / rel).exists():
            return True
    return False


def pull_rebase(klc_dir: Path) -> None:
    """Run ``git pull --rebase`` in *klc_dir*.

    Returns ``None`` on a clean rebase.  If the failure is an actual rebase
    conflict, the in-progress rebase is aborted and :class:`RebaseConflictError`
    is raised.  Any other failure (no upstream, network/auth error, detached
    HEAD, …) is surfaced as a plain :class:`RuntimeError` — it is *not*
    mislabelled as a rebase conflict, and no spurious ``rebase --abort`` is run.
    """
    r = _git(["pull", "--rebase"], klc_dir)
    if r.returncode == 0:
        return

    if _rebase_in_progress(klc_dir):
        _git(["rebase", "--abort"], klc_dir)
        raise RebaseConflictError(r.stderr.strip() or r.stdout.strip())

    raise RuntimeError(
        f"git pull --rebase failed in {klc_dir}: "
        f"{r.stderr.strip() or r.stdout.strip()}"
    )


# Derived / runtime-local artifacts inside the klc-state worktree that must
# never be tracked or pushed (C-003: board/index/prompt-cards are DERIVED from
# per-ticket meta; the lock is process-local). Kept out of the tracked tree via
# the worktree's git exclude file so they never dirty it, never block a
# ``pull --rebase``, and are never swept into the ticket-subtree glob-commit.
# Patterns without a slash match at any depth (so per-ticket ``.lock`` /
# ``_prompt.md`` under ``tickets/<KEY>/<phase>/`` are covered).
_DERIVED_IGNORES = (
    "knowledge/tickets-index.jsonl",  # derived cross-ticket index cache
    ".lock",                          # per-ticket runtime lock (held in-tx)
    ".index.json",                    # per-ticket derived inline-items index
    "_prompt.md",                     # derived phase prompt card
    "_prompt_step_*.md",              # derived build step cards
)


def ensure_clean(klc_dir: Path) -> None:
    """Force the TRACKED worktree back to a pristine ``HEAD`` before a pull.

    Every successful feature-on op commits+pushes, so the tree is clean between
    ops; any dirty *tracked* state on enter is a never-pushed crash/leftover
    artifact and the remote (restored by the subsequent pull) is the source of
    truth.  Unstage everything, then discard working-tree modifications to
    tracked files.  Untracked / git-ignored files (e.g. the derived index cache
    and prompt cards) are intentionally preserved — they neither block a rebase
    nor ride a commit.  Never raises: a non-repo / detached dir is a silent
    no-op (the caller's pull will surface any real problem).
    """
    _git(["reset", "-q"], klc_dir)             # index → HEAD (unstage all)
    _git(["checkout", "-q", "--", "."], klc_dir)  # worktree tracked → HEAD


def ensure_derived_ignored(klc_dir: Path) -> None:
    """Ensure the derived local caches are git-ignored in this worktree.

    Appends the derived-cache paths to the worktree's ``info/exclude`` (a LOCAL,
    per-clone ignore that is never shared or committed) so an append to the
    derived index never shows as an untracked change and never blocks a rebase.
    Idempotent and never raises.
    """
    klc_dir = Path(klc_dir)
    r = _git(["rev-parse", "--git-path", "info/exclude"], klc_dir)
    if r.returncode != 0 or not r.stdout.strip():
        return
    exclude = Path(r.stdout.strip())
    if not exclude.is_absolute():
        exclude = klc_dir / exclude
    try:
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        present = set(existing.split())
        missing = [rule for rule in _DERIVED_IGNORES if rule not in present]
        if not missing:
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            for rule in missing:
                fh.write(rule + "\n")
    except OSError:
        pass


def _upstream_branch(klc_dir: Path) -> str:
    """Return the *branch name* the current branch tracks (no remote prefix).

    Resolves ``branch.<local>.merge`` (``refs/heads/<name>``) so that a local
    branch whose name differs from its upstream still pushes to the tracked
    branch, and branch names containing ``/`` are handled correctly.
    """
    cur = _git(["rev-parse", "--abbrev-ref", "HEAD"], klc_dir)
    branch = cur.stdout.strip()
    merge = _git(["config", "--get", f"branch.{branch}.merge"], klc_dir)
    ref = merge.stdout.strip()
    prefix = "refs/heads/"
    if ref.startswith(prefix):
        return ref[len(prefix):]
    # Fall back to stripping the remote prefix from `<remote>/<branch>`.
    up = _git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        klc_dir,
    )
    val = up.stdout.strip()
    return val.split("/", 1)[1] if "/" in val else val


def _incoming_same_ticket_paths(
    prefix: str, klc_dir: Path, upstream_ref: str = "@{upstream}"
) -> list[str]:
    """Return sorted ``tickets/<ticket>/`` paths touched by incoming commits.

    Enumerates every ``HEAD..<upstream_ref>`` commit and diffs each against its
    own first parent with rename detection, unioning both the source and
    destination of every changed/renamed path.  *upstream_ref* is the tracking
    ref of the remote actually being pushed to (which may differ from
    ``@{upstream}`` when a non-default *remote* is used).
    """
    rev = _git(["rev-list", f"HEAD..{upstream_ref}"], klc_dir)
    if rev.returncode != 0:
        # An unresolvable ref must not be silently read as "no incoming paths"
        # (which would miss a same-ticket conflict) — surface it clearly.
        raise RuntimeError(
            f"git rev-list HEAD..{upstream_ref} failed: "
            f"{rev.stderr.strip() or rev.stdout.strip()}"
        )
    touched: set[str] = set()
    for sha in rev.stdout.split():
        show = _git(
            ["show", "--first-parent", "-M", "--name-status", "--format=", sha],
            klc_dir,
        )
        for line in show.stdout.splitlines():
            fields = [f.strip() for f in line.split("\t") if f.strip()]
            if len(fields) < 2:
                continue  # skip the status-only / blank header lines
            # fields[0] is the status (M/A/D/R<score>/C<score>); the remaining
            # fields are path(s) — for renames/copies both old AND new.
            touched.update(fields[1:])
    return sorted(f for f in touched if f.startswith(prefix))


def commit_and_push_cas(
    paths,
    msg: str,
    ticket: str,
    klc_dir: Path,
    remote: str = "origin",
    max_retries: int = 3,
) -> None:
    """Stage *paths*, commit *msg*, and push to *remote* with CAS semantics.

    The commit is always pushed with an explicit ``HEAD:<upstream_branch>``
    refspec, where ``<upstream_branch>`` is the branch name the current branch
    tracks (borrowed from its configured upstream).  This targets the intended
    branch even when the local branch name differs from it, and — for a
    non-default *remote* — pushes to that branch on *remote* rather than to a
    branch named after the local branch.

    Conflict classification and rebase read the tip actually fetched from
    *remote*:

    * When *remote* is the current branch's configured upstream remote (the
      default ``origin`` case), ``@{upstream}`` is used — it resolves custom
      fetch refspecs correctly (the tracking ref is not always
      ``<remote>/<branch>``).
    * For any other *remote*, ``<upstream_branch>`` is fetched from it
      explicitly and ``FETCH_HEAD`` is used, without assuming any
      tracking-ref naming.

    Only a genuine non-fast-forward rejection enters the CAS loop; any other
    push rejection (protected branch, pre-receive hook, …) is surfaced directly
    as a :class:`RuntimeError`.  On a non-fast-forward the incoming commits are
    inspected per-commit, each diffed against its own first parent with rename
    detection (see :func:`_incoming_same_ticket_paths`), so that changes made
    through merge commits, rename sources moving a file *out* of the ticket, and
    same-ticket changes later reverted by another incoming commit are all
    surfaced — without falsely flagging paths a merge's second parent merely
    reintroduces from already-local history:

    * If any remote change touches ``tickets/<ticket>/`` the push is a
      single-writer violation and :class:`StateConflictError` is raised
      immediately (no retry).
    * Otherwise the remote change is absorbed via rebase and the push is
      retried, up to *max_retries* times, after which
      :class:`RetryExhaustedError` is raised.

    On any terminal failure (:class:`StateConflictError`,
    :class:`RetryExhaustedError`, :class:`RebaseConflictError`, or a
    non-classifiable push/fetch error) the just-created local commit is
    unwound with ``git reset --soft HEAD~1`` so it does not pollute the next
    CAS cycle; the working-tree changes are preserved.

    Raises:
        ValueError: if a path does not exist, or ``git add`` refuses a path
            (before any commit is made).
        ConfigError: if *klc_dir* has no configured upstream.
        NothingToCommitError: if the supplied paths have no staged changes.
    """
    klc_dir = Path(klc_dir)

    # Materialise once (paths may be a generator) and require at least one:
    # an empty pathspec would make `git add`/`git commit` operate on the whole
    # index and commit unrelated already-staged content.
    paths = list(paths)
    if not paths:
        raise ValueError("commit_and_push_cas requires at least one path")

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
    upstream_branch = _upstream_branch(klc_dir)

    str_paths = [str(p) for p in paths]

    # Stage ONLY the supplied paths; fail loudly if git refuses any of them
    # (ignored file, path outside the worktree, …) so we never fall through to
    # committing unrelated already-staged content.
    add = _git(["add", "--", *str_paths], klc_dir)
    if add.returncode != 0:
        raise ValueError(
            f"git add refused a path: {add.stderr.strip() or add.stdout.strip()}"
        )

    # Commit ONLY the supplied paths (pathspec-limited) so pre-staged, unrelated
    # content is never swept into this commit.
    commit = _git(["commit", "-m", msg, "--", *str_paths], klc_dir)
    if commit.returncode != 0:
        out = (commit.stdout + commit.stderr).lower()
        if "nothing to commit" in out or "no changes added" in out:
            raise NothingToCommitError(
                commit.stdout.strip() or commit.stderr.strip()
                or "nothing to commit"
            )
        raise RuntimeError(commit.stderr.strip() or commit.stdout.strip())

    # Classification and rebase must read the tip that was actually fetched from
    # the remote we are pushing to.  When that remote IS the branch's configured
    # upstream, reuse @{upstream} — it already resolves custom fetch refspecs
    # (the tracking ref is not always ``<remote>/<branch>``) and is the AC-2
    # path.  For any OTHER remote, the branch is fetched explicitly and we work
    # off FETCH_HEAD, never assuming a ``<remote>/<branch>`` tracking ref.
    cur_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], klc_dir).stdout.strip()
    upstream_remote = _git(
        ["config", "--get", f"branch.{cur_branch}.remote"], klc_dir
    ).stdout.strip()
    use_upstream = remote == upstream_remote

    try:
        _push_with_cas(
            ticket, upstream_branch, use_upstream, klc_dir, remote, max_retries
        )
    except Exception:
        # Terminal failure: unwind the local commit (keep the changes staged)
        # so the next CAS cycle starts clean.
        _git(["reset", "--soft", "HEAD~1"], klc_dir)
        raise


def commit_and_push_cas_subtree(
    ticket: str,
    msg: str,
    klc_dir: Path,
    remote: str = "origin",
    max_retries: int = 3,
) -> None:
    """Glob-commit EVERYTHING under ``tickets/<ticket>/`` and CAS-push it.

    The design-hardened counterpart to :func:`commit_and_push_cas`: instead of a
    hand-listed path fragment it stages the ticket's whole subtree with
    ``git add -A -- tickets/<ticket>/`` (adds, modifications AND deletions), so
    any file the verb body wrote under the subtree — meta.json, raw.md,
    ``_superseded/…``, a jira-merged raw.md — is captured automatically and no
    mutation site can be "forgotten." Conflict classification, rebase, retry and
    the terminal ``reset --soft`` unwind are shared with the CAS machinery.

    Raises:
        ConfigError: if *klc_dir* has no configured upstream.
        ValueError: if ``git add`` refuses the subtree (before any commit).
        NothingToCommitError: if the subtree had no staged changes.
        StateConflictError / RetryExhaustedError / RebaseConflictError /
        RuntimeError: per the CAS push semantics.
    """
    klc_dir = Path(klc_dir)
    subtree = f"tickets/{ticket}/"

    up = _git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        klc_dir,
    )
    if up.returncode != 0:
        raise ConfigError(
            f"no upstream configured for current branch in {klc_dir}"
        )
    upstream_branch = _upstream_branch(klc_dir)

    # Stage the ENTIRE subtree (``-A`` captures deletions from supersede moves).
    add = _git(["add", "-A", "--", subtree], klc_dir)
    if add.returncode != 0:
        raise ValueError(
            f"git add refused {subtree!r}: {add.stderr.strip() or add.stdout.strip()}"
        )

    commit = _git(["commit", "-m", msg, "--", subtree], klc_dir)
    if commit.returncode != 0:
        out = (commit.stdout + commit.stderr).lower()
        if "nothing to commit" in out or "no changes added" in out:
            raise NothingToCommitError(
                commit.stdout.strip() or commit.stderr.strip()
                or "nothing to commit"
            )
        raise RuntimeError(commit.stderr.strip() or commit.stdout.strip())

    cur_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], klc_dir).stdout.strip()
    upstream_remote = _git(
        ["config", "--get", f"branch.{cur_branch}.remote"], klc_dir
    ).stdout.strip()
    use_upstream = remote == upstream_remote

    try:
        _push_with_cas(
            ticket, upstream_branch, use_upstream, klc_dir, remote, max_retries
        )
    except Exception:
        _git(["reset", "--soft", "HEAD~1"], klc_dir)
        raise


def _push_with_cas(
    ticket: str,
    upstream_branch: str,
    use_upstream: bool,
    klc_dir: Path,
    remote: str,
    max_retries: int,
) -> None:
    prefix = f"tickets/{ticket}/"
    attempt = 0
    while True:
        push = _git(["push", remote, f"HEAD:{upstream_branch}"], klc_dir)
        if push.returncode == 0:
            return

        err = (push.stderr or "").lower()
        # Only a genuine write-race rejection is a CAS conflict worth absorbing.
        # A bare "rejected" for a NON-race reason (protected branch, pre-receive
        # hook, …) is a server-side policy rejection: surface it directly rather
        # than looping through fetch/rebase/retry and masking it as
        # RetryExhaustedError.  The race markers below cover both the plain
        # non-fast-forward case and the concurrent ref-lock contention that
        # occurs when the remote advances mid-push.
        if not any(m in err for m in _CAS_RACE_MARKERS):
            raise RuntimeError(
                (push.stderr or "").strip() or push.stdout.strip()
            )

        # Absorb the tip of the ref we push to.  For the branch's own upstream
        # remote, a plain fetch updates @{upstream}; for any other remote we
        # fetch the branch explicitly and use FETCH_HEAD (no tracking-ref-naming
        # assumption).  A failed fetch means the ref is stale — classifying
        # against it would silently mask a real network/auth error, so surface
        # it instead.
        if use_upstream:
            fetch = _git(["fetch", remote], klc_dir)
            classify_ref = "@{upstream}"
        else:
            fetch = _git(["fetch", remote, upstream_branch], klc_dir)
            classify_ref = "FETCH_HEAD"
        if fetch.returncode != 0:
            raise RuntimeError(
                f"git fetch {remote} failed while resolving CAS conflict on "
                f"{ticket}: {fetch.stderr.strip() or fetch.stdout.strip()}"
            )

        # Classify by the UNION of paths touched across the incoming commits.
        # `git rev-list HEAD..<classify_ref>` enumerates every commit only on the
        # pushed remote (including those reachable only via a merge's second
        # parent, so merge visibility is preserved), and each commit is diffed
        # against its own FIRST parent.  First-parent-per-commit avoids
        # re-counting paths that a merge's second parent merely reintroduces from
        # already-local history (no false other-ticket conflict); `-M
        # --name-status` surfaces rename SOURCE paths (so moving a file out of
        # our ticket still counts); and enumerating each commit catches a
        # same-ticket change a later commit reverts (net-zero tree).
        same_ticket = _incoming_same_ticket_paths(prefix, klc_dir, classify_ref)
        if same_ticket:
            raise StateConflictError(
                f"same-ticket single-writer violation on {ticket}: "
                f"remote touched {same_ticket}"
            )

        if attempt >= max_retries:
            raise RetryExhaustedError(
                f"push rejected after {max_retries} retr"
                f"{'y' if max_retries == 1 else 'ies'} on {ticket}"
            )

        rebase = _git(["rebase", classify_ref], klc_dir)
        if rebase.returncode != 0:
            _git(["rebase", "--abort"], klc_dir)
            raise RebaseConflictError(rebase.stderr.strip())
        attempt += 1
