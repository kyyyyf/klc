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
