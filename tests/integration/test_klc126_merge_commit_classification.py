"""tests/integration/test_klc126_merge_commit_classification.py — KLC-126
step-1 AC-6: `tdd_order.classify` must classify a non-conflicting merge
commit by its first-parent diff (`git show --first-parent -M -C
--name-status --format=`), not by the empty combined-diff file list plain
`git show --name-only --format=` produces for a clean merge (KLC-109
review round 4 pre-existing INFO finding, code-review-findings.json).

Empirically verified (git 2.43, throwaway `/tmp` repos, this ticket's own
discovery pass) against the shipped, UNMODIFIED `9da9889` `classify`:

- merge bringing in only test-shaped changes    -> pre-fix "impl" (GENUINE RED)
- merge bringing in only production changes     -> pre-fix "impl" (REGRESSION
  PIN — right answer today via the wrong, empty-list-default mechanism)
- merge bringing in mixed changes                -> pre-fix "impl" (GENUINE RED)
- merge with an empty first-parent diff          -> pre-fix "impl" (REGRESSION
  PIN — the fail-closed default, unaffected by the fix)

Uses the same `_make_repo`/`_run` fixture-repo scaffold as
`tests/integration/test_klc109_tdd_order.py`, with an explicit `main`
branch name so merge behaviour does not depend on the host's
`init.defaultBranch` config.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.tdd_order import classify, verify_step  # noqa: E402


def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, capture_output=True, text=True, cwd=str(cwd))
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.email", "test@test.com"], repo)
    _run(["git", "config", "user.name", "Test User"], repo)
    return repo


def _commit(repo: Path, files: dict[str, str], subject: str) -> str:
    for relpath, content in files.items():
        p = repo / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _run(["git", "add", relpath], repo)
    _run(["git", "commit", "-m", subject], repo)
    return _run(["git", "rev-parse", "HEAD"], repo)


def _merge(repo: Path, branch: str, subject: str) -> str:
    """Merge *branch* into the current branch with --no-ff and return the
    new merge commit's sha."""
    _run(["git", "merge", "--no-ff", branch, "-m", subject], repo)
    return _run(["git", "rev-parse", "HEAD"], repo)


def test_merge_commit_bringing_in_only_test_changes_classifies_as_test(tmp_path):
    """AC-6: a --no-ff merge whose first-parent diff introduces only a
    test-shaped file (with its sibling already present pre-merge)
    classifies as test, not the pre-fix default impl from an empty
    combined-diff list."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/a.go": "package pkg\n"}, "base: add pkg/a.go")
    _run(["git", "checkout", "-b", "side"], repo)
    _commit(repo, {"pkg/a_test.go": "package pkg\n"}, "side: add pkg/a_test.go")
    _run(["git", "checkout", "main"], repo)
    sha = _merge(repo, "side", "KLC-T126 step-1: merge side (test only) into main")

    status = _run(["git", "show", "--first-parent", "-M", "-C", "--name-status",
                   "--format=", sha], repo)
    assert status, "expected a non-empty first-parent diff for this merge"

    assert classify(sha, repo) == "test"


def test_merge_commit_bringing_in_only_production_changes_classifies_as_impl(tmp_path):
    """AC-6 negative twin: a merge whose first-parent diff introduces ONLY a
    production file (no sibling) classifies impl, and a step whose sole
    commit is that merge is sanctioned, for the RIGHT reason (a real
    first-parent diff showing production-only content) — not the old
    accidental 'empty file list defaults to impl' behaviour."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/base.go": "package pkg\n"}, "base: add pkg/base.go")
    _run(["git", "checkout", "-b", "side"], repo)
    _commit(repo, {"pkg/c.go": "package pkg\n"}, "side: add pkg/c.go (production, no sibling)")
    _run(["git", "checkout", "main"], repo)
    sha = _merge(repo, "side", "KLC-T126 step-1: merge side (production only) into main")

    status = _run(["git", "show", "--first-parent", "-M", "-C", "--name-status",
                   "--format=", sha], repo)
    assert status, "expected a non-empty first-parent diff for this merge"

    assert classify(sha, repo) == "impl"
    ok, reason = verify_step("KLC-T126", 1, repo)
    assert not ok, f"expected sanction (ok=False), got ok=True reason={reason!r}"


def test_merge_commit_bringing_in_mixed_changes_classifies_as_mixed(tmp_path):
    """AC-6: a merge whose first-parent diff introduces both a test-shaped
    and a production-shaped file in the same commit classifies mixed,
    proving the first-parent diff is actually consulted rather than
    short-circuited by the empty combined-diff default."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/base.go": "package pkg\n"}, "base: add pkg/base.go")
    _run(["git", "checkout", "-b", "side"], repo)
    _commit(repo, {"pkg/e_test.go": "package pkg\n", "pkg/f.go": "package pkg\n"},
            "side: add test-shaped and production files")
    _run(["git", "checkout", "main"], repo)
    sha = _merge(repo, "side", "KLC-T126 step-1: merge side (mixed) into main")

    status = _run(["git", "show", "--first-parent", "-M", "-C", "--name-status",
                   "--format=", sha], repo)
    assert status, "expected a non-empty first-parent diff for this merge"

    assert classify(sha, repo) == "mixed"


def test_merge_commit_with_empty_first_parent_diff_still_degrades_to_impl(tmp_path):
    """AC-6 fail-closed twin: a genuinely no-op merge (first-parent diff
    introduces nothing, because both parents already carry identical
    content for the only file involved) must still degrade to
    classify() == "impl", matching the pre-existing `if not files: return
    "impl"` default; never mis-degrades to "test"."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/base.go": "package pkg\n"}, "base: add pkg/base.go")
    _run(["git", "checkout", "-b", "side"], repo)
    _commit(repo, {"pkg/g.go": "same content\n"}, "side: add pkg/g.go")
    _run(["git", "checkout", "main"], repo)
    _commit(repo, {"pkg/g.go": "same content\n"},
            "main: independently add identical pkg/g.go")
    sha = _merge(repo, "side",
                 "KLC-T126 step-1: merge side (identical content already present) into main")

    status = _run(["git", "show", "--first-parent", "-M", "-C", "--name-status",
                   "--format=", sha], repo)
    assert status == "", f"expected an EMPTY first-parent diff, got: {status!r}"

    assert classify(sha, repo) == "impl"
