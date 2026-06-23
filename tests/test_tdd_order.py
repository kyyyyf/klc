"""KLC-039: tdd_order — commit classification and step-ordering verifier."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.tdd_order import classify, step_commits, verify_step  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers: synthetic isolated git repo
# ---------------------------------------------------------------------------

def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, capture_output=True, text=True, cwd=str(cwd))
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@test.com"], repo)
    _run(["git", "config", "user.name", "Test User"], repo)
    return repo


def _commit(repo: Path, files: dict[str, str], subject: str) -> str:
    """Write files, stage, commit; return the commit SHA."""
    for relpath, content in files.items():
        p = repo / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _run(["git", "add", relpath], repo)
    _run(["git", "commit", "-m", subject], repo)
    return _run(["git", "rev-parse", "HEAD"], repo)


# ---------------------------------------------------------------------------
# step_commits
# ---------------------------------------------------------------------------

def test_step_commits_returns_oldest_first(tmp_path):
    """AC-1: step_commits lists the step's commits oldest→newest."""
    repo = _make_repo(tmp_path)
    sha1 = _commit(repo, {"tests/test_x.py": "# test"}, "KLC-XXX step-1: add test")
    sha2 = _commit(repo, {"src/x.py": "# impl"}, "KLC-XXX step-1: add impl")
    commits = step_commits("KLC-XXX", 1, repo)
    assert len(commits) == 2
    assert commits[0]["sha"] == sha1
    assert commits[1]["sha"] == sha2


def test_step_commits_filters_by_step(tmp_path):
    """step_commits returns only commits for the requested step."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"tests/test_x.py": "# test"}, "KLC-XXX step-1: add test")
    sha2 = _commit(repo, {"src/y.py": "# y"}, "KLC-XXX step-2: add y")
    commits = step_commits("KLC-XXX", 2, repo)
    assert len(commits) == 1
    assert commits[0]["sha"] == sha2


def test_step_commits_empty_when_no_match(tmp_path):
    """step_commits returns [] when no commits match the pattern."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"src/z.py": "# z"}, "unrelated commit")
    commits = step_commits("KLC-XXX", 1, repo)
    assert commits == []


def test_step_commits_empty_on_missing_repo(tmp_path):
    """step_commits degrades gracefully on a missing/invalid repo path."""
    missing = tmp_path / "nonexistent"
    commits = step_commits("KLC-XXX", 1, missing)
    assert commits == []


def test_step_commits_does_not_match_step_ten(tmp_path):
    """step_commits for step-1 must not return commits for step-10."""
    repo = _make_repo(tmp_path)
    # step-10 commits — should NOT appear when querying step-1
    _commit(repo, {"tests/test_x.py": "# test"}, "KLC-XXX step-10: add test")
    _commit(repo, {"src/x.py": "# impl"}, "KLC-XXX step-10: add impl")
    commits = step_commits("KLC-XXX", 1, repo)
    assert commits == [], f"step-1 should return [] when only step-10 commits exist; got: {commits}"


def test_step_commits_step_ten_not_matched_by_step_one(tmp_path):
    """Both step-1 and step-10 commits exist; each step only sees its own."""
    repo = _make_repo(tmp_path)
    sha1 = _commit(repo, {"tests/test_x.py": "# test"}, "KLC-XXX step-1: add test")
    sha10 = _commit(repo, {"tests/test_y.py": "# test y"}, "KLC-XXX step-10: add test")
    commits_1 = step_commits("KLC-XXX", 1, repo)
    commits_10 = step_commits("KLC-XXX", 10, repo)
    assert len(commits_1) == 1 and commits_1[0]["sha"] == sha1
    assert len(commits_10) == 1 and commits_10[0]["sha"] == sha10


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

def test_classify_tests_only(tmp_path):
    """AC-1: a commit touching only tests/ files is classified 'test'."""
    repo = _make_repo(tmp_path)
    sha = _commit(repo, {"tests/test_foo.py": "# test"}, "add test")
    assert classify(sha, repo) == "test"


def test_classify_impl_only(tmp_path):
    """AC-1: a commit touching only source files is classified 'impl'."""
    repo = _make_repo(tmp_path)
    sha = _commit(repo, {"core/skills/foo.py": "# impl"}, "add impl")
    assert classify(sha, repo) == "impl"


def test_classify_mixed(tmp_path):
    """AC-1: a commit touching both tests/ and source files is classified 'mixed'."""
    repo = _make_repo(tmp_path)
    sha = _commit(
        repo,
        {"tests/test_foo.py": "# test", "core/skills/foo.py": "# impl"},
        "add both",
    )
    assert classify(sha, repo) == "mixed"


def test_classify_nested_test_path(tmp_path):
    """tests/integration/... paths are classified as 'test'."""
    repo = _make_repo(tmp_path)
    sha = _commit(repo, {"tests/integration/test_bar.py": "# int test"}, "add int test")
    assert classify(sha, repo) == "test"


# ---------------------------------------------------------------------------
# verify_step — step-2 tests (kept in same file per impl-plan)
# ---------------------------------------------------------------------------

def test_verify_step_ordered_passes(tmp_path):
    """AC-1/AC-2: failing-test commit then impl commit → ok=True."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"tests/test_x.py": "# failing test"}, "KLC-T01 step-1: add failing test")
    _commit(repo, {"core/x.py": "# impl"}, "KLC-T01 step-1: make test pass")
    ok, reason = verify_step("KLC-T01", 1, repo)
    assert ok, f"expected ok=True for ordered history, got reason={reason!r}"
    assert reason == ""


def test_verify_step_impl_first_sanctions(tmp_path):
    """AC-2: impl commit first, no preceding test commit → ok=False with reason."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"core/x.py": "# impl first"}, "KLC-T02 step-1: add impl")
    _commit(repo, {"tests/test_x.py": "# test added later"}, "KLC-T02 step-1: add test after")
    ok, reason = verify_step("KLC-T02", 1, repo)
    assert not ok, "expected ok=False: impl commit precedes test commit"
    assert "KLC-T02 step-1" in reason


def test_verify_step_no_test_commit_sanctions(tmp_path):
    """AC-2: no test commit at all for the step → ok=False."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"core/y.py": "# impl only"}, "KLC-T03 step-1: add impl only")
    ok, reason = verify_step("KLC-T03", 1, repo)
    assert not ok, "expected ok=False: no test commit for step"
    assert "KLC-T03 step-1" in reason


def test_verify_step_mixed_first_sanctions(tmp_path):
    """AC-2: a 'mixed' commit as the first commit → ok=False (order unprovable)."""
    repo = _make_repo(tmp_path)
    _commit(
        repo,
        {"tests/test_x.py": "# test", "core/x.py": "# impl"},
        "KLC-T04 step-1: mixed commit",
    )
    ok, reason = verify_step("KLC-T04", 1, repo)
    assert not ok, "expected ok=False: mixed commit has no prior red test commit"
    assert "KLC-T04 step-1" in reason


def test_verify_step_no_commits_sanctions(tmp_path):
    """AC-2: no commits match the step pattern → ok=False with clear reason."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"src/z.py": "# unrelated"}, "unrelated commit")
    ok, reason = verify_step("KLC-T05", 1, repo)
    assert not ok, "expected ok=False when no step commits found"
    assert "KLC-T05 step-1" in reason


def test_verify_step_degrades_on_missing_repo(tmp_path):
    """Edge case: missing/invalid repo → ok=False with clear reason (no crash)."""
    missing = tmp_path / "nonexistent"
    ok, reason = verify_step("KLC-T06", 1, missing)
    assert not ok
    assert "KLC-T06 step-1" in reason
