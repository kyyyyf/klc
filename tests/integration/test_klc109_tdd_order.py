"""tests/integration/test_klc109_tdd_order.py — KLC-109 step-3: the
red-before-green ordering gate recognises filename-adjacent test commits
(no `tests/` directory needed) and honours the active profile's table.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.tdd_order import classify, verify_step  # noqa: E402
import test_conventions as _tc  # noqa: E402

_ENGINE_MANIFEST = (
    _FW_ROOT / "tests" / "fixtures" / "klc109-engine-profile" / "manifest.yml"
)


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


FILENAME_ADJACENT_LAYOUTS = [
    ("Foo.test.tsx", "Foo.tsx"),
    ("foo_test.go", "foo.go"),
    ("FooTest.java", "Foo.java"),
    ("foo_spec.rb", "foo.rb"),
    # D-109-12, scenario (f): a plain-JS colocated pair through the
    # verify_step/classify pipeline (round-2's HIGH #1 fix already covers
    # this at the pure is_test_path level in test_test_conventions.py; this
    # exercises it through the git-commit classification path too).
    ("Foo.spec.js", "Foo.js"),
]


@pytest.mark.parametrize("test_path,impl_path", FILENAME_ADJACENT_LAYOUTS)
def test_verify_step_passes_filename_adjacent_red_then_green(tmp_path, test_path, impl_path):
    """AC-6: verify_step returns ok=True for a fixture repo with NO tests/
    directory whose step-1 history is a test-only commit followed by a
    production-only commit, for every filename-adjacent layout."""
    repo = _make_repo(tmp_path)
    _commit(repo, {test_path: "# failing test"}, "KLC-T109 step-1: add failing test")
    _commit(repo, {impl_path: "# impl"}, "KLC-T109 step-1: make test pass")
    ok, reason = verify_step("KLC-T109", 1, repo)
    assert ok, f"{test_path}/{impl_path}: expected ok=True, got reason={reason!r}"


@pytest.mark.parametrize("test_path,impl_path", FILENAME_ADJACENT_LAYOUTS)
def test_verify_step_sanctions_reversed_order_filename_adjacent(tmp_path, test_path, impl_path):
    """AC-6 negative twin: the same four layouts, impl commit BEFORE the test
    commit, must still be sanctioned."""
    repo = _make_repo(tmp_path)
    _commit(repo, {impl_path: "# impl first"}, "KLC-T109 step-1: add impl")
    _commit(repo, {test_path: "# test added later"}, "KLC-T109 step-1: add test after")
    ok, reason = verify_step("KLC-T109", 1, repo)
    assert not ok, f"{test_path}/{impl_path}: expected ok=False for reversed order"
    assert "KLC-T109 step-1" in reason


def test_verify_step_recognises_ue_spec_cpp_through_active_table(tmp_path, monkeypatch):
    """AC-5/AC-6 (F-2 end-to-end row): with the table parsed from a real,
    on-disk manifest.yml (the D-OP-1 synthetic engine-style fixture standing
    in for the deleted profiles/ue/manifest.yml — see test-plan.md's
    Revision note), a red commit touching only Source/Foo/Private/FooSpec.cpp
    followed by a green commit touching only Source/Foo/Private/Foo.cpp
    passes verify_step; with builtin_table() active the SAME history is
    sanctioned, so this row cannot pass vacuously."""
    import yaml  # dev/test dependency only — imported lazily so the per-test
    # conftest fixture (_restore_real_pyyaml) has already run and undone any
    # core/shared/yaml.py shadow a full-suite run may have left in sys.modules
    manifest = yaml.safe_load(_ENGINE_MANIFEST.read_text(encoding="utf-8"))
    engine_table = _tc.table_from_manifest(manifest)

    repo = _make_repo(tmp_path)
    _commit(repo, {"Source/Foo/Private/FooSpec.cpp": "// spec"},
           "KLC-T109 step-1: add failing spec")
    _commit(repo, {"Source/Foo/Private/Foo.cpp": "// impl"},
           "KLC-T109 step-1: make spec pass")

    _tc._reset_active_table_cache_for_tests()
    monkeypatch.setattr(_tc, "_read_profile_conventions",
                        lambda: manifest["test_conventions"])
    try:
        ok, reason = verify_step("KLC-T109", 1, repo)
        assert ok, f"expected ok=True under the engine-style table, got reason={reason!r}"
    finally:
        _tc._reset_active_table_cache_for_tests()

    monkeypatch.setattr(_tc, "_read_profile_conventions", lambda: None)
    try:
        ok, reason = verify_step("KLC-T109", 1, repo)
        assert not ok, "expected ok=False under builtin_table() — the row would be vacuous otherwise"
    finally:
        _tc._reset_active_table_cache_for_tests()

    # Sanity: the engine table really does classify FooSpec.cpp as a test and
    # builtin_table() really does not (else the two verify_step outcomes above
    # would not be attributable to the table difference at all).
    # exists=lambda *_: True per the AC-2 amendment (D-109-9's conservative
    # default requires a confirmed sibling for a basename-only match).
    assert _tc.is_test_path("Source/Foo/Private/FooSpec.cpp", table=engine_table,
                            exists=lambda *_: True) is True
    assert _tc.is_test_path("Source/Foo/Private/FooSpec.cpp",
                            table=_tc.builtin_table(), exists=lambda *_: True) is False


def test_verify_step_sanctions_bare_commit_to_shared_modules_own_basename(tmp_path):
    """AC-6 review-fix (D-109-7, code-review HIGH): a step whose SOLE commit
    touches only a core/skills/test_map.py-shaped path — a python `test_*.py`
    basename with NO sibling production file beside it, and no `tests/`
    directory — must be SANCTIONED as an unguarded implementation commit,
    never waved through as 'only test commits, ordering is fine'. This is
    the exact gate-bypass the fresh code-reviewer found: before the fix,
    `classify()` called `is_test_path()` with no root, so the basename glob
    alone made this commit look like a test.

    Round 4 (D-109-12) update: `test_map.py` now PRE-EXISTS in a bootstrap
    commit (not part of the step) before the step's own commit edits it —
    under the per-commit new-file rule, an ADDED test-shaped path needs no
    sibling yet (that is precisely what fixes the mid-step RED-only false
    sanction, see the tests below); this fixture's whole point is a
    PRE-EXISTING path with no sibling, which must still be `impl`."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"core/skills/test_map.py": "# initial bootstrap content"},
            "bootstrap: initial repo scaffold")
    sha = _commit(repo, {"core/skills/test_map.py": "# a real implementation change"},
                 "KLC-T109 step-1: change test_map.py")
    assert classify(sha, repo) == "impl", "no map.py sibling exists — must classify impl"
    ok, reason = verify_step("KLC-T109", 1, repo)
    assert not ok, (
        "expected ok=False: a bare production commit shaped like "
        f"test_map.py must not pass as 'only test commits'; got reason={reason!r}"
    )


def test_verify_step_still_passes_when_shared_modules_sibling_exists(tmp_path):
    """AC-6 review-fix negative-of-the-negative: the sibling rule is
    conservative, not punitive — a python `test_*.py`-shaped file DOES still
    classify as a test once its derived sibling (`map.py`) exists beside it,
    so ordinary colocated python layouts are unaffected."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"core/skills/map.py": "# impl"}, "KLC-T109 step-1: add impl")
    sha = _commit(repo, {"core/skills/test_map.py": "# test"},
                 "KLC-T109 step-1: add test")
    assert classify(sha, repo) == "test"


# ---------------------------------------------------------------------------
# Review round 3 -> round 4 (D-109-12, supersedes D-109-10, code-review HIGH):
# drop step-tip anchoring; classify PER COMMIT against its own two immutable
# git trees (own + parent). A freshly-ADDED basename match needs no sibling
# yet (fixes the mid-step RED-only false sanction); a PRE-EXISTING one still
# does (keeps the round-1/round-2 self-referential-collision fix intact).
# Temporal stability now follows from git's own tree immutability.
# ---------------------------------------------------------------------------

def test_verify_step_ok_for_mid_step_red_only_commit(tmp_path):
    """AC-6 review round 3 HIGH / D-109-12, scenario (a): a step whose ONLY
    landed commit is its RED test — the GREEN commit not yet committed, the
    exact ordinary mid-flight TDD window every step of every ticket passes
    through — must NOT be sanctioned. Under the round-2 (D-109-10) step-tip
    design, this exact commit WAS its own tip, its own tree had no confirmed
    sibling yet, and it was misclassified `impl`, producing a false,
    backwards 'implementation commit found with no preceding failing-test
    commit' sanction."""
    repo = _make_repo(tmp_path)
    sha = _commit(repo, {"pkg/foo_test.go": "# failing test"},
                 "KLC-T109 step-1: add failing test")
    assert classify(sha, repo) == "test", (
        "a freshly-added basename match needs no sibling confirmed yet"
    )
    ok, reason = verify_step("KLC-T109", 1, repo)
    assert ok, f"expected ok=True for a lone RED commit, got reason={reason!r}"
    assert reason == ""


def test_verify_step_stays_ok_after_same_step_fixup_removes_the_sibling(tmp_path):
    """AC-6 review round 3 HIGH / D-109-12, scenario (c): a THIRD commit,
    still labelled with the SAME step, that removes the just-added
    production sibling after a passing RED+GREEN pair must not
    retroactively flip the step's verdict. Under the round-2 (D-109-10)
    step-tip design, the step's tip moved to this fix-up commit, whose OWN
    tree no longer had the sibling, and the already-passing step flipped to
    a false sanction. Under per-commit classification, the GREEN commit's
    own classification never changes — it is an immutable fact about that
    one commit and its (also immutable) parent tree."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/foo_test.go": "# failing test"}, "KLC-T109 step-1: add failing test")
    _commit(repo, {"pkg/foo.go": "# impl"}, "KLC-T109 step-1: make test pass")
    ok_before, reason_before = verify_step("KLC-T109", 1, repo)
    assert ok_before, f"expected ok=True after RED+GREEN, got {reason_before!r}"

    _run(["git", "rm", "pkg/foo.go"], repo)
    _run(["git", "commit", "-m", "KLC-T109 step-1: fixup remove foo.go"], repo)

    ok_after, reason_after = verify_step("KLC-T109", 1, repo)
    assert ok_after == ok_before, (
        f"same-step fix-up flipped the verdict: before={ok_before!r}/{reason_before!r} "
        f"after={ok_after!r}/{reason_after!r}"
    )


def test_classify_pre_existing_test_shaped_file_modified_alone_with_sibling_present_is_test(tmp_path):
    """AC-6 review round 3 LOW-adjacent / D-109-12, scenario (e): a
    `test_map.py` that already exists (NOT added by this commit) is still a
    test when its sibling `map.py` already exists too — modifying
    `test_map.py`'s content alone must classify `test` via the `exists=`
    path (the sibling is confirmed), not the `added=` path (the file is not
    new)."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"core/skills/map.py": "# impl"}, "bootstrap: add impl")
    _commit(repo, {"core/skills/test_map.py": "# test v1"}, "bootstrap: add test")
    sha = _commit(repo, {"core/skills/test_map.py": "# test v2 — content only"},
                 "KLC-T109 step-1: update test_map.py")
    assert classify(sha, repo) == "test"


# ---------------------------------------------------------------------------
# Review round 2 (D-109-10, code-review HIGH #2): the sibling-existence probe
# is backed by a git tree, not today's working-tree checkout, and it is
# anchored to the STEP'S OWN LAST commit — so an already-acked step's verdict
# cannot flip because a LATER, unrelated commit deletes the sibling.
# ---------------------------------------------------------------------------

def test_verify_step_stays_stable_after_a_later_unrelated_commit_deletes_the_sibling(tmp_path):
    """HIGH #2 exact repro: step-1 commits pkg/foo_test.go (RED) then
    pkg/foo.go (GREEN) — verify_step correctly returns ok=True right after
    both land. A THIRD, LATER, UNRELATED commit then removes pkg/foo.go (a
    legitimate refactor with no `step-1` in its subject). Re-running
    verify_step for step-1 — with NO change to step-1's own commits — must
    return the SAME ok=True verdict: an acked step's TDD-ordering result
    must not depend on what unrelated later history does to a sibling
    file."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"pkg/foo_test.go": "# failing test"}, "KLC-T109 step-1: add failing test")
    _commit(repo, {"pkg/foo.go": "# impl"}, "KLC-T109 step-1: make test pass")
    ok_before, reason_before = verify_step("KLC-T109", 1, repo)
    assert ok_before, f"expected ok=True right after both commits land, got {reason_before!r}"

    # A later, unrelated commit (no step-1 in its subject) removes the sibling.
    _run(["git", "rm", "pkg/foo.go"], repo)
    _run(["git", "commit", "-m", "unrelated refactor: drop pkg/foo.go"], repo)

    ok_after, reason_after = verify_step("KLC-T109", 1, repo)
    assert ok_after == ok_before, (
        f"step-1's verdict flipped after an UNRELATED later commit: "
        f"before={ok_before!r}/{reason_before!r} after={ok_after!r}/{reason_after!r}"
    )


def test_classify_sibling_probe_reads_the_tree_not_the_working_directory(tmp_path):
    """HIGH #2: classify's exists= probe must never touch the live working
    tree at all — deleting the file ON DISK (but not via a commit) must not
    change classify's answer for a commit whose OWN historical tree still
    has the sibling."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"core/skills/map.py": "# impl"}, "KLC-T109 step-1: add impl")
    sha = _commit(repo, {"core/skills/test_map.py": "# test"},
                 "KLC-T109 step-1: add test")
    assert classify(sha, repo) == "test"

    # Delete map.py from the WORKING TREE only (no new commit) — classify
    # must still answer from the git tree, not the live checkout.
    (repo / "core" / "skills" / "map.py").unlink()
    assert classify(sha, repo) == "test", (
        "classify() must read the commit's own git tree, not today's "
        "working-tree checkout"
    )
