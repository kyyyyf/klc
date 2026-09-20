"""tests/integration/test_klc126_tdd_order_rename_merge.py — KLC-126 step-1
AC-1..AC-5: `tdd_order.classify` must key off real git rename/copy status
(`git show --first-parent -M -C --name-status --format=`), not a bare
`--name-only` file list, so a pure `git mv production.x production_test.x`
(KLC-109 review round 4 MEDIUM, code-review-findings.json) can no longer
pass `verify_step` unguarded.

Empirically verified (git 2.43, throwaway `/tmp` repos, this ticket's own
discovery pass) against the shipped, UNMODIFIED `9da9889` `classify`:

- pure rename, no content change            -> pre-fix "test" (GENUINE RED)
- rename + small content edit (R069)        -> pre-fix "test" (GENUINE RED)
- copy w/ source modified in same commit    -> pre-fix "mixed" (REGRESSION PIN
  — already correct today, but via the wrong mechanism: an unconditional
  `added=` bypass on the copy destination that happens to land on the same
  aggregate answer because the source survives)
- genuinely new test-shaped file, no sibling -> pre-fix "test" (REGRESSION PIN,
  D-109-12's own fix)
- git mv inside a declared test directory   -> pre-fix "test" (REGRESSION PIN,
  directory signal never consults exists=/added=)
- invalid/unreachable commit sha            -> pre-fix "impl" (REGRESSION PIN,
  fail-closed default)

Uses the same `_make_repo`/`_run` fixture-repo scaffold as
`tests/integration/test_klc109_tdd_order.py`.
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
    _run(["git", "init"], repo)
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


def _commit_staged(repo: Path, subject: str) -> str:
    """Commit whatever is already staged (e.g. by a preceding `git mv`)."""
    _run(["git", "commit", "-m", subject], repo)
    return _run(["git", "rev-parse", "HEAD"], repo)


def test_rename_only_commit_with_no_content_change_is_sanctioned(tmp_path):
    """AC-1: a pure git mv of a production file to a test-shaped basename,
    with no accompanying content change and no confirmed production
    sibling, classifies as impl (not test), so a step whose only commit is
    `git mv production.go production_test.go` is sanctioned (verify_step
    returns ok=False) instead of silently passing as 'only test commits'."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/foo.go": "package pkg\n\nfunc Foo() int {\n\treturn 1\n}\n"},
            "bootstrap: add foo.go (not part of the step under test)")
    _run(["git", "mv", "pkg/foo.go", "pkg/foo_test.go"], repo)
    sha = _commit_staged(repo, "KLC-T126 step-1: rename foo.go to foo_test.go (no content change)")

    status = _run(["git", "show", "--first-parent", "-M", "-C", "--name-status",
                   "--format=", sha], repo)
    assert status.startswith("R"), f"expected an R### rename status, got: {status!r}"

    assert classify(sha, repo) == "impl"
    ok, reason = verify_step("KLC-T126", 1, repo)
    assert not ok, f"expected sanction (ok=False), got ok=True reason={reason!r}"


def test_classify_degrades_to_impl_when_git_status_call_fails(tmp_path):
    """AC-1 fail-closed twin: an invalid/unreachable commit sha (the `git
    show` invocation errors, `_git` returns "") must still degrade to
    classify() == "impl", never raise and never silently default to
    "test" — the same conservative fallback the pre-existing
    `if not files: return "impl"` line already gave, re-pinned under the
    new git invocation."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/base.go": "package pkg\n"}, "bootstrap: add pkg/base.go")
    assert classify("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", repo) == "impl"


def test_rename_with_real_content_change_above_similarity_threshold_still_sanctioned_without_sibling(tmp_path):
    """AC-2: a rename destination that ALSO carries a genuine content edit
    small enough that git still reports R### (not a D+A pair — empirically
    ~69% similarity in this exact fixture) gets the identical
    pre-existing-path treatment as a pure rename: sanctioned, never a free
    added= pass merely because the file also changed."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/foo.go": (
        "package pkg\n\nfunc Foo() int {\n\treturn 1\n}\n\n"
        "func Helper() int {\n\treturn 42\n}\n"
    )}, "bootstrap: add foo.go")
    _run(["git", "mv", "pkg/foo.go", "pkg/foo_test.go"], repo)
    p = repo / "pkg" / "foo_test.go"
    p.write_text(p.read_text() + "\nfunc Extra() int {\n\treturn 99\n}\n")
    _run(["git", "add", "pkg/foo_test.go"], repo)
    sha = _commit_staged(repo, "KLC-T126 step-1: rename with small content addition")

    status = _run(["git", "show", "--first-parent", "-M", "-C", "--name-status",
                   "--format=", sha], repo)
    assert status.split("\t")[0].startswith("R"), (
        f"expected an R### status (rename, not a D+A pair), got: {status!r}"
    )

    assert classify(sha, repo) == "impl"


def test_copy_with_source_modified_in_same_commit_classifies_as_mixed_via_real_sibling(tmp_path):
    """AC-3: a commit that copies a production file to a test-shaped
    destination (C### status — detected because the source is ALSO
    modified in the same commit) classifies as mixed: the copy
    destination's real, still-present sibling confirms it via exists=,
    never via added=, while the still-present modified source keeps its
    own non-test classification."""
    repo = _make_repo(tmp_path)
    content = ("package pkg\n\nfunc Foo() int {\n\treturn 1\n}\n\n"
               "func Helper() int {\n\treturn 42\n}\n")
    _commit(repo, {"pkg/foo.go": content}, "bootstrap: add foo.go")
    (repo / "pkg" / "foo_test.go").write_text(content)
    _run(["git", "add", "pkg/foo_test.go"], repo)
    (repo / "pkg" / "foo.go").write_text(content + "\nfunc Modified() int {\n\treturn 7\n}\n")
    _run(["git", "add", "pkg/foo.go"], repo)
    sha = _commit_staged(repo, "KLC-T126 step-1: copy foo.go to foo_test.go, modify foo.go")

    status = _run(["git", "show", "--first-parent", "-M", "-C", "--name-status",
                   "--format=", sha], repo)
    assert "C" in status, f"expected a C### copy status line, got: {status!r}"

    assert classify(sha, repo) == "mixed"


def test_genuinely_new_test_shaped_file_still_classifies_as_test_no_sibling_required(tmp_path):
    """AC-4: a genuinely new, freshly-authored test-shaped file (a real git
    add, git status A) still classifies as test with no sibling required —
    the round-4 (D-109-12) fix's ordinary mid-flight RED-only commit is not
    regressed by requiring rename/copy detection everywhere."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/base.go": "package pkg\n"}, "bootstrap: add pkg/base.go")
    sha = _commit(repo, {"pkg/z_test.go": "package pkg\n"},
                  "KLC-T126 step-1: add failing test (no sibling yet)")
    assert classify(sha, repo) == "test"


def test_git_mv_of_already_test_shaped_file_inside_test_dir_stays_test(tmp_path):
    """AC-5: a git mv of an already test-shaped file to another test-shaped
    basename inside a declared test directory (tests/test_old_name.py ->
    tests/test_new_name.py, the directory signal, which never consults
    exists=/added=) classifies as test, unaffected by the rename-status
    fix."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"tests/test_old_name.py": "x = 1\n"},
            "bootstrap: add tests/test_old_name.py")
    _run(["git", "mv", "tests/test_old_name.py", "tests/test_new_name.py"], repo)
    sha = _commit_staged(repo, "KLC-T126 step-1: rename inside test dir")
    assert classify(sha, repo) == "test"
