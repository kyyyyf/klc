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
