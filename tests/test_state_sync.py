"""KLC-054: state_sync — git CAS coordination for multi-user .klc/ state.

All tests run entirely against local bare git repos (file paths, no network).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[1]
if str(_FW_ROOT) not in sys.path:
    sys.path.insert(0, str(_FW_ROOT))

from core.skills.state_sync import (  # noqa: E402
    ConfigError,
    NothingToCommitError,
    RebaseConflictError,
    RetryExhaustedError,
    StateConflictError,
    commit_and_push_cas,
    pull_rebase,
)


# ---------------------------------------------------------------------------
# Helpers: local bare repo + working clones (zero network)
# ---------------------------------------------------------------------------

def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)


def _init_bare(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "--bare", "-b", "main", str(path)], path.parent)
    return path


def _clone(origin: Path, dest: Path) -> Path:
    _run(["git", "clone", str(origin), str(dest)], dest.parent)
    _run(["git", "config", "user.email", "test@test.com"], dest)
    _run(["git", "config", "user.name", "Test User"], dest)
    return dest


def _commit_file(repo: Path, relpath: str, content: str, subject: str) -> str:
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _run(["git", "add", "--", relpath], repo)
    _run(["git", "commit", "-m", subject], repo)
    return _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()


def _seed_origin(tmp_path: Path) -> Path:
    """Create a bare origin with one initial commit on `main`. Returns origin."""
    origin = _init_bare(tmp_path / "origin.git")
    seed = _clone(origin, tmp_path / "seed")
    _commit_file(seed, "README.md", "seed\n", "initial commit")
    _run(["git", "push", "-u", "origin", "HEAD:main"], seed)
    return origin


# ---------------------------------------------------------------------------
# AC-1: pull_rebase
# ---------------------------------------------------------------------------

class TestPullRebase:
    def test_clean_pull_rebase(self, tmp_path):
        """AC-1: pull_rebase applies remote commits cleanly and returns None."""
        origin = _seed_origin(tmp_path)
        author = _clone(origin, tmp_path / "author")
        klc = _clone(origin, tmp_path / "klc")

        # Author advances the remote with a new commit.
        _commit_file(author, "b.txt", "two\n", "author: second commit")
        push = _run(["git", "push", "origin", "HEAD:main"], author)
        assert push.returncode == 0, push.stderr

        # klc has no local commits; pull_rebase should fast-forward cleanly.
        assert pull_rebase(klc) is None
        assert (klc / "b.txt").exists()


# ---------------------------------------------------------------------------
# AC-2..AC-4 + edge cases: commit_and_push_cas
# ---------------------------------------------------------------------------

TICKET = "KLC-054"


def _competing_push(origin: Path, tmp_path: Path, name: str,
                    relpath: str, content: str) -> None:
    """A second writer clones origin, commits `relpath`, and pushes to main."""
    other = _clone(origin, tmp_path / name)
    _commit_file(other, relpath, content, f"other: {relpath}")
    push = _run(["git", "push", "origin", "HEAD:main"], other)
    assert push.returncode == 0, push.stderr


class TestCommitAndPushCas:
    def test_fast_forward_push(self, tmp_path):
        """AC-2: clean fast-forward push stages, commits and returns None."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        assert commit_and_push_cas(
            [rel], "KLC-054: ff", TICKET, klc,
        ) is None

        # The commit reached origin/main.
        _run(["git", "fetch", "origin"], klc)
        log = _run(["git", "log", "--format=%s", "origin/main"], klc)
        assert "KLC-054: ff" in log.stdout

    def test_other_ticket_rebase_and_retry(self, tmp_path):
        """AC-3: remote commit OUTSIDE our ticket -> rebase + retry succeeds."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        # Competing writer touches a DIFFERENT ticket.
        _competing_push(origin, tmp_path, "other",
                        "tickets/KLC-099/other.json", "x\n")

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        # First push is rejected (non-ff); absorbs other ticket, retries, wins.
        assert commit_and_push_cas(
            [rel], "KLC-054: mine", TICKET, klc,
        ) is None

        _run(["git", "fetch", "origin"], klc)
        log = _run(["git", "log", "--format=%s", "origin/main"], klc)
        assert "KLC-054: mine" in log.stdout
        assert "tickets/KLC-099/other.json" in _run(
            ["git", "log", "--name-only", "--format=", "origin/main"], klc
        ).stdout

    def test_same_ticket_conflict_raises(self, tmp_path):
        """AC-4: remote commit INSIDE our ticket -> StateConflictError, no retry."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        # Competing writer touches OUR ticket -> single-writer violation.
        _competing_push(origin, tmp_path, "other",
                        f"tickets/{TICKET}/theirs.json", "x\n")

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        with pytest.raises(StateConflictError):
            commit_and_push_cas([rel], "KLC-054: mine", TICKET, klc)

    def test_max_retries_exhausted(self, tmp_path):
        """Other-ticket race with max_retries=0 -> RetryExhaustedError."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        _competing_push(origin, tmp_path, "other",
                        "tickets/KLC-099/other.json", "x\n")

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        with pytest.raises(RetryExhaustedError):
            commit_and_push_cas([rel], "KLC-054: mine", TICKET, klc,
                                max_retries=0)

    def test_nonexistent_path_raises_value_error(self, tmp_path):
        """A path that does not exist -> ValueError before any git op."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        head_before = _run(["git", "rev-parse", "HEAD"], klc).stdout.strip()

        with pytest.raises(ValueError):
            commit_and_push_cas(
                [f"tickets/{TICKET}/missing.json"], "KLC-054: x", TICKET, klc,
            )
        # No commit was created.
        assert _run(["git", "rev-parse", "HEAD"], klc).stdout.strip() == head_before

    def test_missing_upstream_raises_config_error(self, tmp_path):
        """No upstream configured -> ConfigError."""
        repo = tmp_path / "solo"
        repo.mkdir()
        _run(["git", "init", "-b", "main", str(repo)], tmp_path)
        _run(["git", "config", "user.email", "test@test.com"], repo)
        _run(["git", "config", "user.name", "Test User"], repo)
        _commit_file(repo, "README.md", "solo\n", "initial")
        rel = f"tickets/{TICKET}/state.json"
        (repo / "tickets" / TICKET).mkdir(parents=True)
        (repo / rel).write_text("{}\n", encoding="utf-8")

        with pytest.raises(ConfigError):
            commit_and_push_cas([rel], "KLC-054: x", TICKET, repo)


# ---------------------------------------------------------------------------
# Review-fix regression tests (KLC-054 review-fix)
# ---------------------------------------------------------------------------

class TestReviewFixes:
    def test_push_targets_upstream_branch_not_local_name(self, tmp_path):
        """P2: local branch name != upstream branch — push must target upstream.

        The worktree's local branch is renamed so it no longer matches the
        tracked ``origin/main``.  A ``git push origin HEAD`` would create a
        remote branch named after the LOCAL branch and leave ``main`` stale;
        the fix must push ``HEAD:main`` so the tracked branch receives the
        commit and no stray branch is created.
        """
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        _run(["git", "branch", "-m", "worklocal"], klc)
        assert _run(
            ["git", "rev-parse", "--abbrev-ref", "@{upstream}"], klc
        ).stdout.strip() == "origin/main"

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        assert commit_and_push_cas(
            [rel], "KLC-054: upstream", TICKET, klc,
        ) is None

        _run(["git", "fetch", "origin"], klc)
        assert "KLC-054: upstream" in _run(
            ["git", "log", "--format=%s", "origin/main"], klc
        ).stdout
        heads = _run(["git", "ls-remote", "--heads", "origin"], klc).stdout
        assert "refs/heads/main" in heads
        assert "refs/heads/worklocal" not in heads

    def test_rollback_after_state_conflict(self, tmp_path):
        """MED: the just-created local commit is unwound on StateConflictError."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        _competing_push(origin, tmp_path, "other",
                        f"tickets/{TICKET}/theirs.json", "x\n")

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")
        head_before = _run(["git", "rev-parse", "HEAD"], klc).stdout.strip()

        with pytest.raises(StateConflictError):
            commit_and_push_cas([rel], "KLC-054: mine", TICKET, klc)

        head_after = _run(["git", "rev-parse", "HEAD"], klc).stdout.strip()
        assert head_after == head_before  # local commit rolled back
        assert (klc / rel).exists()       # soft reset preserves the change

    def test_fetch_failure_raises_clear_error_not_retry_exhausted(self, tmp_path):
        """MED: a failed fetch after non-ff must raise, not loop to exhaustion.

        The push URL points at the real origin (so the push is genuinely
        rejected as non-ff), while the fetch URL is broken — mimicking a
        network/auth failure.  The old code ignored the fetch exit code and
        misclassified the (stale) upstream, ending in RetryExhaustedError.
        """
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        _competing_push(origin, tmp_path, "other",
                        "tickets/KLC-099/o.json", "x\n")
        _run(["git", "remote", "set-url", "--push", "origin", str(origin)], klc)
        _run(["git", "remote", "set-url", "origin",
              str(tmp_path / "does-not-exist.git")], klc)

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")
        head_before = _run(["git", "rev-parse", "HEAD"], klc).stdout.strip()

        with pytest.raises(RuntimeError) as ei:
            commit_and_push_cas([rel], "KLC-054: mine", TICKET, klc)
        assert not isinstance(ei.value, (RetryExhaustedError, StateConflictError))
        # terminal failure rolls the local commit back
        assert _run(["git", "rev-parse", "HEAD"], klc).stdout.strip() == head_before

    def test_git_add_failure_does_not_commit_unrelated(self, tmp_path):
        """P2: a refused `git add` must raise and never commit staged leftovers."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        # Ignore the ticket tree so `git add` refuses the path.
        (klc / ".gitignore").write_text("tickets/\n", encoding="utf-8")
        _run(["git", "add", ".gitignore"], klc)
        _run(["git", "commit", "-q", "-m", "ignore tickets"], klc)
        # Pre-stage an UNRELATED change that must not be committed.
        (klc / "README.md").write_text("tampered\n", encoding="utf-8")
        _run(["git", "add", "README.md"], klc)

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")  # exists but ignored
        head_before = _run(["git", "rev-parse", "HEAD"], klc).stdout.strip()

        with pytest.raises((ValueError, RuntimeError)):
            commit_and_push_cas([rel], "KLC-054: x", TICKET, klc)
        # No commit created -> the unrelated staged content never landed.
        assert _run(["git", "rev-parse", "HEAD"], klc).stdout.strip() == head_before

    def test_nothing_to_commit_raises_typed_error(self, tmp_path):
        """LOW: an unchanged path yields a clearly-typed NothingToCommitError."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")
        _run(["git", "add", "--", rel], klc)
        _run(["git", "commit", "-q", "-m", "pre"], klc)

        with pytest.raises(NothingToCommitError):
            commit_and_push_cas([rel], "KLC-054: noop", TICKET, klc)

    def test_remote_commit_touching_both_tickets_raises_conflict(self, tmp_path):
        """A single remote commit touching same- AND other-ticket -> conflict."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        other = _clone(origin, tmp_path / "other")
        (other / f"tickets/{TICKET}").mkdir(parents=True)
        (other / f"tickets/{TICKET}/theirs.json").write_text("x\n", encoding="utf-8")
        (other / "tickets/KLC-099").mkdir(parents=True)
        (other / "tickets/KLC-099/o.json").write_text("y\n", encoding="utf-8")
        _run(["git", "add", "-A"], other)
        _run(["git", "commit", "-q", "-m", "both tickets"], other)
        push = _run(["git", "push", "origin", "HEAD:main"], other)
        assert push.returncode == 0, push.stderr

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        with pytest.raises(StateConflictError):
            commit_and_push_cas([rel], "KLC-054: mine", TICKET, klc)

    def test_evil_merge_commit_surfaced_via_three_dot(self, tmp_path):
        """LOW: a merge commit that touches our ticket must be surfaced.

        Two-dot ``git log --name-only`` emits nothing for a merge commit, so
        the evil merge's same-ticket change is invisible; the three-dot
        merge-base diff surfaces it and must raise StateConflictError.
        """
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        other = _clone(origin, tmp_path / "other")

        _run(["git", "checkout", "-q", "-b", "feature"], other)
        (other / "tickets/KLC-099").mkdir(parents=True)
        (other / "tickets/KLC-099/a.json").write_text("x\n", encoding="utf-8")
        _run(["git", "add", "-A"], other)
        _run(["git", "commit", "-q", "-m", "feat KLC-099"], other)
        _run(["git", "checkout", "-q", "main"], other)
        _run(["git", "merge", "--no-ff", "--no-commit", "feature"], other)
        (other / f"tickets/{TICKET}").mkdir(parents=True)
        (other / f"tickets/{TICKET}/evil.json").write_text("z\n", encoding="utf-8")
        _run(["git", "add", "--", f"tickets/{TICKET}/evil.json"], other)
        _run(["git", "commit", "-q", "--no-edit"], other)
        push = _run(["git", "push", "origin", "HEAD:main"], other)
        assert push.returncode == 0, push.stderr

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        with pytest.raises(StateConflictError):
            commit_and_push_cas([rel], "KLC-054: mine", TICKET, klc)

    def test_multi_race_retries_across_iterations(self, tmp_path):
        """A pre-push hook injects a fresh other-ticket race on each attempt,
        forcing >1 retry iteration; the CAS must absorb both and finally win."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        racer = _clone(origin, tmp_path / "racer")
        count_file = tmp_path / "race_count"

        hook = klc / ".git" / "hooks" / "pre-push"
        hook.write_text(
            "#!/bin/sh\n"
            f'CF="{count_file}"\n'
            f'RACER="{racer}"\n'
            'c=$(cat "$CF" 2>/dev/null || echo 0)\n'
            'if [ "$c" -lt 2 ]; then\n'
            '  c=$((c+1)); echo "$c" > "$CF"\n'
            '  cd "$RACER" || exit 0\n'
            '  git fetch -q origin\n'
            '  git reset -q --hard origin/main\n'
            '  mkdir -p tickets/KLC-099\n'
            '  echo x > "tickets/KLC-099/r$c.json"\n'
            '  git add -A\n'
            '  git commit -q -m "race $c"\n'
            '  git push -q origin HEAD:main\n'
            'fi\n',
            encoding="utf-8",
        )
        hook.chmod(0o755)

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        assert commit_and_push_cas(
            [rel], "KLC-054: mine", TICKET, klc, max_retries=5,
        ) is None

        assert count_file.read_text().strip() == "2"  # two races injected
        _run(["git", "fetch", "origin"], klc)
        log = _run(["git", "log", "--format=%s", "origin/main"], klc).stdout
        assert "KLC-054: mine" in log
        assert "race 1" in log and "race 2" in log

    def test_non_ff_marker_required_non_cas_rejection_raises_clear_error(
        self, tmp_path
    ):
        """P2a(r2): a non-CAS 'rejected' (protected branch / pre-receive hook)
        must raise a clear error, NOT be sent through the CAS retry loop."""
        origin = _seed_origin(tmp_path)
        # Server rejects EVERY push for a non-CAS reason (bare 'rejected',
        # no 'non-fast-forward' / 'fetch first' marker).
        hook = origin / "hooks" / "pre-receive"
        hook.write_text(
            "#!/bin/sh\necho 'policy: branch is protected' >&2\nexit 1\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        klc = _clone(origin, tmp_path / "klc")
        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")
        head_before = _run(["git", "rev-parse", "HEAD"], klc).stdout.strip()

        with pytest.raises(RuntimeError) as ei:
            commit_and_push_cas([rel], "KLC-054: mine", TICKET, klc)
        assert not isinstance(ei.value, (RetryExhaustedError, StateConflictError))
        # terminal failure still rolls the local commit back
        assert _run(["git", "rev-parse", "HEAD"], klc).stdout.strip() == head_before

    def test_self_reverting_same_ticket_commit_raises_conflict(self, tmp_path):
        """P2b(r2): a remote that touches our ticket then reverts it (net-zero
        tree) must still raise StateConflictError — per-commit classification,
        not the net three-dot diff."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        other = _clone(origin, tmp_path / "other")

        # Commit 1: touch OUR ticket.
        (other / f"tickets/{TICKET}").mkdir(parents=True)
        (other / f"tickets/{TICKET}/theirs.json").write_text("x\n", encoding="utf-8")
        _run(["git", "add", "-A"], other)
        _run(["git", "commit", "-q", "-m", "add same-ticket"], other)
        # Commit 2: revert that change (net-zero for our ticket) but keep an
        # unrelated file so the branch is genuinely ahead.
        _run(["git", "rm", "-q", "--", f"tickets/{TICKET}/theirs.json"], other)
        (other / "tickets/KLC-099").mkdir(parents=True)
        (other / "tickets/KLC-099/keep.json").write_text("k\n", encoding="utf-8")
        _run(["git", "add", "-A"], other)
        _run(["git", "commit", "-q", "-m", "revert same-ticket, keep other"], other)
        push = _run(["git", "push", "origin", "HEAD:main"], other)
        assert push.returncode == 0, push.stderr

        (klc / "tickets" / TICKET).mkdir(parents=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        with pytest.raises(StateConflictError):
            commit_and_push_cas([rel], "KLC-054: mine", TICKET, klc)

    def test_other_ticket_merge_second_parent_not_false_conflict(self, tmp_path):
        """P2a(r3): a normal OTHER-ticket merge whose 2nd parent predates an
        already-local same-ticket file must NOT be misreported as a conflict
        (per-commit first-parent classification, no 2nd-parent double-count)."""
        origin = _seed_origin(tmp_path)  # S0 seed on main
        seed_clone = _clone(origin, tmp_path / "seedc")
        # S1: add a same-ticket file into the shared history.
        (seed_clone / f"tickets/{TICKET}").mkdir(parents=True)
        (seed_clone / f"tickets/{TICKET}/base.json").write_text("b\n", encoding="utf-8")
        _run(["git", "add", "-A"], seed_clone)
        _run(["git", "commit", "-q", "-m", "add base"], seed_clone)
        _run(["git", "push", "origin", "HEAD:main"], seed_clone)

        klc = _clone(origin, tmp_path / "klc")     # at S1 (HEAD has base.json)
        other = _clone(origin, tmp_path / "other")  # at S1
        # feature branches from S0 (before base.json) and does OTHER-ticket work.
        _run(["git", "checkout", "-q", "-b", "feature", "HEAD~1"], other)
        (other / "tickets/KLC-099").mkdir(parents=True)
        (other / "tickets/KLC-099/f.json").write_text("f\n", encoding="utf-8")
        _run(["git", "add", "-A"], other)
        _run(["git", "commit", "-q", "-m", "feat KLC-099"], other)
        _run(["git", "checkout", "-q", "main"], other)
        _run(["git", "merge", "--no-edit", "feature"], other)
        push = _run(["git", "push", "origin", "HEAD:main"], other)
        assert push.returncode == 0, push.stderr

        (klc / f"tickets/{TICKET}").mkdir(parents=True, exist_ok=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        # OTHER-ticket race -> rebase + retry succeeds (no false StateConflictError).
        assert commit_and_push_cas(
            [rel], "KLC-054: mine", TICKET, klc,
        ) is None
        _run(["git", "fetch", "origin"], klc)
        assert "KLC-054: mine" in _run(
            ["git", "log", "--format=%s", "origin/main"], klc
        ).stdout

    def test_rename_out_of_ticket_raises_conflict(self, tmp_path):
        """P2b(r3): a rename moving a file OUT of our ticket dir touches our
        ticket via the SOURCE path and must raise StateConflictError."""
        origin = _seed_origin(tmp_path)
        seed_clone = _clone(origin, tmp_path / "seedc")
        (seed_clone / f"tickets/{TICKET}").mkdir(parents=True)
        (seed_clone / f"tickets/{TICKET}/a.json").write_text("aaa\n", encoding="utf-8")
        _run(["git", "add", "-A"], seed_clone)
        _run(["git", "commit", "-q", "-m", "add a"], seed_clone)
        _run(["git", "push", "origin", "HEAD:main"], seed_clone)

        klc = _clone(origin, tmp_path / "klc")     # has tickets/KLC-054/a.json
        other = _clone(origin, tmp_path / "other")
        (other / "tickets/KLC-099").mkdir(parents=True)
        _run(["git", "mv", f"tickets/{TICKET}/a.json",
              "tickets/KLC-099/a.json"], other)
        _run(["git", "commit", "-q", "-m", "rename out of ticket"], other)
        push = _run(["git", "push", "origin", "HEAD:main"], other)
        assert push.returncode == 0, push.stderr

        (klc / f"tickets/{TICKET}").mkdir(parents=True, exist_ok=True)
        rel = f"tickets/{TICKET}/state.json"
        (klc / rel).write_text("{}\n", encoding="utf-8")

        with pytest.raises(StateConflictError):
            commit_and_push_cas([rel], "KLC-054: mine", TICKET, klc)

    def test_empty_paths_raises_without_committing(self, tmp_path):
        """P2c(r3): empty paths must raise before any git op and never commit
        pre-staged, unrelated content."""
        origin = _seed_origin(tmp_path)
        klc = _clone(origin, tmp_path / "klc")
        # Pre-stage unrelated content that must NOT be committed.
        (klc / "README.md").write_text("tampered\n", encoding="utf-8")
        _run(["git", "add", "README.md"], klc)
        head_before = _run(["git", "rev-parse", "HEAD"], klc).stdout.strip()

        with pytest.raises(ValueError):
            commit_and_push_cas([], "KLC-054: x", TICKET, klc)

        assert _run(["git", "rev-parse", "HEAD"], klc).stdout.strip() == head_before
        _run(["git", "fetch", "origin"], klc)
        assert "KLC-054: x" not in _run(
            ["git", "log", "--format=%s", "origin/main"], klc
        ).stdout


class TestPullRebaseErrors:
    def test_no_upstream_not_labeled_rebase_conflict(self, tmp_path):
        """LOW: a non-conflict pull_rebase failure must not be RebaseConflictError."""
        repo = tmp_path / "solo"
        repo.mkdir()
        _run(["git", "init", "-q", "-b", "main", str(repo)], tmp_path)
        _run(["git", "config", "user.email", "test@test.com"], repo)
        _run(["git", "config", "user.name", "Test User"], repo)
        _commit_file(repo, "r.txt", "x\n", "init")

        # No remote/upstream -> pull --rebase fails, but no rebase is started.
        with pytest.raises(RuntimeError) as ei:
            pull_rebase(repo)
        assert not isinstance(ei.value, RebaseConflictError)
