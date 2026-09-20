"""tests/test_test_conventions.py — KLC-109 step-1/step-2: the shared
per-language test-path convention table.

Every test function below carries its AC id in its own docstring/body (the
ac_test_coverage gate scans per FUNCTION, not the module docstring).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_file_dir = Path(__file__).resolve().parent
_FIXTURES = _file_dir / "fixtures"
sys.path.insert(0, str(_file_dir.parent / "core" / "skills"))

import test_conventions as tc  # noqa: E402


# ---------------------------------------------------------------------------
# AC-2: is_test_path is True for every named per-language test layout.
# ---------------------------------------------------------------------------

AC2_NAMED_LAYOUTS = [
    # python
    "tests/test_x.py",
    "pkg/tests/integration/test_x.py",
    "x_test.py",
    "conftest.py",
    # js/ts
    "Foo.test.tsx",
    "Foo.test.ts",
    "Foo.spec.js",
    "__tests__/Foo.ts",
    "src/__tests__/a.jsx",
    # go
    "foo_test.go",
    # rust
    "tests/integration.rs",
    "foo_test.rs",
    "src/tests.rs",
    # java/kotlin
    "FooTest.java",
    "FooTests.java",
    "FooTest.kt",
    "src/test/java/p/Foo.java",
    # c#
    "FooTests.cs",
    "FooTest.cs",
    "App.Tests/Foo.cs",
    # ruby
    "foo_spec.rb",
    "spec/models/foo_spec.rb",
    "test/foo_test.rb",
    # cpp
    "foo_test.cpp",
    "FooTest.cpp",
    "test/foo.cpp",
    "Source/AppTests/Foo.cpp",
    # extras from test-plan.md's edge cases
    "__tests__/Foo.tsx",   # dir-only signal, no `.test.` infix
    "foo/tests.rs",        # nested tests.rs, not only the top-level src/tests.rs case
]


@pytest.mark.parametrize("path", AC2_NAMED_LAYOUTS)
def test_is_test_path_true_for_named_layouts(path):
    """AC-2 (operator amendment 2026-09-20, D-109-9): is_test_path returns
    True for every named per-language test layout once the caller confirms
    the layout's derived sibling exists — a directory-signalled layout
    (`tests/test_x.py`) and a 'sibling: none' layout (`conftest.py`) need no
    confirmation at all; a bare basename-signal layout outside a test
    directory (`x_test.py`, `Foo.test.tsx`, `foo_test.go`, ...) needs one.
    `exists=lambda *_: True` proves the SHAPE recognition in isolation from
    the existence gate, which AC-6 tests separately."""
    assert tc.is_test_path(path, exists=lambda *_: True) is True, path


# ---------------------------------------------------------------------------
# AC-3: is_test_path is False for near-miss production paths.
# ---------------------------------------------------------------------------

AC3_NEAR_MISSES = [
    "contests/foo.py",
    "src/latest.py",
    "app/protest.ts",
    "pkg/attestation.go",
    "src/testing/util.go",
    "Manifest.cs",
    "src/Contest.tsx",
    # extras from test-plan.md's edge cases
    "testing_utils.py",
    "latest_report.py",
    "src/attest/x.ts",
    "protest.go",
]


@pytest.mark.parametrize("path", AC3_NEAR_MISSES)
def test_is_test_path_false_for_near_miss_paths(path):
    """AC-3: is_test_path returns False for near-miss production paths — a
    substring match can never classify production code as a test."""
    assert tc.is_test_path(path) is False, path


# ---------------------------------------------------------------------------
# AC-4 / D-204: production_candidates emits a deterministic order.
# ---------------------------------------------------------------------------

AC4_PAIRINGS = [
    ("tests/test_x.py", ["x.py"]),
    ("x_test.py", ["x.py"]),
    ("__tests__/Foo.test.ts", ["Foo.ts", "Foo.tsx"]),
    ("Foo.test.tsx", ["Foo.tsx"]),
    ("foo_test.go", ["foo.go"]),
    ("FooTest.java", ["Foo.java"]),
    ("src/test/java/p/FooTest.java", ["src/main/java/p/Foo.java"]),
    ("FooTests.cs", ["Foo.cs"]),
    ("spec/foo_spec.rb", ["foo.rb"]),
    ("foo_test.cpp", ["foo.cpp", "foo.h"]),
]


@pytest.mark.parametrize("path,expected_prefix", AC4_PAIRINGS)
def test_production_candidates_maps_named_pairs(path, expected_prefix):
    """AC-4: production_candidates returns the production paths a test file
    pairs with, in deterministic order."""
    cands = tc.production_candidates(path)
    assert cands[: len(expected_prefix)] == expected_prefix, (path, cands)


def test_production_candidates_multiple_for_ambiguous_java_src_test_layout():
    """AC-4: src/test/java/p/FooTest.java returns several candidates (at
    least src/main/java/p/Foo.java); the caller resolves against its own
    file universe per Q-005."""
    cands = tc.production_candidates("src/test/java/p/FooTest.java")
    assert len(cands) >= 2
    assert cands[0] == "src/main/java/p/Foo.java"


@pytest.mark.parametrize("path", ["src/app/Foo.py", "not-a-path-at-all"])
def test_production_candidates_empty_for_unrecognised_or_non_test_path(path):
    """AC-4: an unrecognised path returns an empty list without raising."""
    assert tc.production_candidates(path) == []


# ---------------------------------------------------------------------------
# AC-1: the module's public API works for all eight languages, no I/O.
# ---------------------------------------------------------------------------

REPRESENTATIVE_PATHS = {
    "python": "tests/test_x.py",
    "js-ts": "Foo.test.tsx",
    "go": "foo_test.go",
    "rust": "foo_test.rs",
    "java-kotlin": "FooTest.java",
    "csharp": "FooTests.cs",
    "ruby": "foo_spec.rb",
    "cpp": "foo_test.cpp",
}


@pytest.mark.parametrize("lang,path", sorted(REPRESENTATIVE_PATHS.items()))
def test_module_exposes_public_api_for_all_eight_languages(lang, path):
    """AC-1: is_test_path/production_candidates are importable and callable
    for a representative path in each of the eight named languages
    (`exists=lambda *_: True` per the AC-2 amendment — see that test)."""
    assert tc.is_test_path(path, exists=lambda *_: True) is True, (lang, path)
    assert tc.production_candidates(path) != [], (lang, path)


def test_no_io_on_either_call_path(monkeypatch):
    """AC-1: no index read, no git call and no filesystem I/O on either call
    path — the default (table=None) call never invokes subprocess or opens a
    file."""
    def _boom(*a, **k):
        raise AssertionError("unexpected I/O on the default call path")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(Path, "open", _boom)
    monkeypatch.setattr("os.stat", _boom)
    for path in REPRESENTATIVE_PATHS.values():
        tc.is_test_path(path)
        tc.production_candidates(path)


# ---------------------------------------------------------------------------
# D-204 / F-3: the four ordering rows the review demanded a code sketch for.
# ---------------------------------------------------------------------------

def test_candidates_prefer_the_test_files_own_extension_jsts():
    """AC-4/D-204 (js/ts): Foo.test.tsx yields Foo.tsx at index 0, Foo.ts
    after it — the test file's OWN extension is preferred over table order."""
    cands = tc.production_candidates("Foo.test.tsx")
    assert cands[0] == "Foo.tsx"
    assert "Foo.ts" in cands[1:]


def test_candidates_dir_rewrite_before_dir_drop_java():
    """AC-4/D-204 (java): src/test/java/p/FooTest.java yields the dir-REWRITE
    src/main/java/p/Foo.java at index 0, the dir-DROPPED src/java/p/Foo.java
    after it."""
    cands = tc.production_candidates("src/test/java/p/FooTest.java")
    assert cands[0] == "src/main/java/p/Foo.java"
    assert "src/java/p/Foo.java" in cands[1:]


def test_candidates_dir_drop_before_same_dir_python():
    """AC-4/D-204 (python): tests/test_x.py yields the dir-DROPPED x.py at
    index 0, the SAME-dir tests/x.py after it."""
    cands = tc.production_candidates("tests/test_x.py")
    assert cands[0] == "x.py"
    assert "tests/x.py" in cands[1:]


def test_candidates_same_dir_when_no_test_directory_go():
    """AC-4/D-204 (go): pkg/foo_test.go yields pkg/foo.go at index 0 — go has
    no test_dirs, so SAME is the only directory form."""
    cands = tc.production_candidates("pkg/foo_test.go")
    assert cands[0] == "pkg/foo.go"


# ---------------------------------------------------------------------------
# D-109-6 (found during step-7's guard work, dogfooding this ticket's own
# git history): the DIRECTORY signal must be extension-agnostic — a fixture
# file under tests/ with an extension no LangRules record owns (.yml, .json,
# ...) must still be a test, exactly like the old tests/-segment-only rule.
# ---------------------------------------------------------------------------

def test_is_test_path_true_for_non_language_file_under_a_test_directory():
    """AC-1/AC-2/C-001: a fixture file with an extension no LangRules record
    owns is STILL a test when it lives under a recognised test directory
    (tests/, __tests__/, spec/, ...) — the directory signal does not depend
    on the file's extension. Regression: KLC-109's own build committed
    tests/fixtures/klc109-*/manifest.yml (.yml) alongside
    tests/test_test_conventions.py (.py) in one commit; an extension-gated
    directory check misclassified that commit 'mixed' instead of 'test'."""
    assert tc.is_test_path("tests/fixtures/klc109-profile/manifest.yml") is True
    assert tc.is_test_path("tests/data.json") is True
    assert tc.is_test_path("__tests__/fixture.yaml") is True


def test_is_test_path_false_for_non_language_file_outside_a_test_directory():
    """AC-3/C-003-style negative twin: a non-language file OUTSIDE any
    recognised test directory stays False — the extension-agnostic directory
    signal must not become a second, broader substring trap."""
    assert tc.is_test_path("config/settings.yml") is False
    assert tc.is_test_path("contests/data.yml") is False


# ---------------------------------------------------------------------------
# AC-5 / step-2: a profile extends the table through a manifest key, resolved
# at ONE point (D-203).
# ---------------------------------------------------------------------------

def test_manifest_test_conventions_key_extends_builtin_table():
    """AC-5: a fixture manifest.yml's test_conventions: key adds a glob/dir/
    stem rule the built-in table misses, and is_test_path/production_candidates
    recognise the added pattern."""
    import yaml  # dev/test dependency only — imported lazily so the per-test
    # conftest fixture (_restore_real_pyyaml) has already run and undone any
    # core/shared/yaml.py shadow a full-suite run may have left in sys.modules
    manifest = yaml.safe_load(
        (_FIXTURES / "klc109-profile" / "manifest.yml").read_text(encoding="utf-8"))
    table = tc.table_from_manifest(manifest)
    # The added test_dirs entry ("qa") is not part of the built-in table.
    assert tc.is_test_path("qa/check_x.py", table=tc.builtin_table()) is False
    assert tc.is_test_path("qa/check_x.py", table=table) is True
    # The added test_globs entry ("check_*.py") plus its stem rule
    # (exists=lambda *_: True per the AC-2 amendment — see that test).
    assert tc.is_test_path("check_x.py", table=tc.builtin_table()) is False
    assert tc.is_test_path("check_x.py", table=table, exists=lambda *_: True) is True
    assert "x.py" in tc.production_candidates("check_x.py", table=table)


@pytest.mark.parametrize("manifest", [
    {},                                                    # absent key
    {"test_conventions": "not-a-dict"},                     # wrong type
    {"test_conventions": {"test_dirs": 123, "test_globs": 123,
                          "stem_rules": 123}},              # schema-invalid entries
])
def test_manifest_absent_or_malformed_degrades_to_builtin_no_raise(manifest):
    """AC-5: an absent or malformed test_conventions: key leaves the built-in
    table untouched and raises nothing."""
    assert tc.table_from_manifest(manifest) == tc.builtin_table()


def test_active_table_resolves_the_profile_key_once_and_caches(monkeypatch):
    """AC-5/D-203/F-2: active_table() resolves the active profile's
    test_conventions: block ONCE per process (module-level cache) — the field
    resolver is invoked exactly once across repeated calls."""
    tc._reset_active_table_cache_for_tests()
    calls = []

    def _fake_reader():
        calls.append(1)
        return None

    monkeypatch.setattr(tc, "_read_profile_conventions", _fake_reader)
    tc.active_table()
    tc.active_table()
    tc.active_table()
    assert len(calls) == 1
    tc._reset_active_table_cache_for_tests()


def test_active_table_degrades_to_builtin_when_profile_unreadable(monkeypatch):
    """AC-5/C-001/D-203: the field resolver raising, timing out or returning
    non-JSON yields builtin_table() and no exception escapes the hard ack
    gate."""
    tc._reset_active_table_cache_for_tests()

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="profile-resolve.py", timeout=10)

    monkeypatch.setattr(subprocess, "run", _boom)
    assert tc.active_table() == tc.builtin_table()
    tc._reset_active_table_cache_for_tests()


def test_ue_manifest_declares_tests_dir_and_star_tests_cpp_layout():
    """AC-5: a synthetic engine-style profile fixture (D-OP-1 — profiles/ue/**
    was deleted by KLC-122; 'ue' in this test's name denotes the synthetic
    fixture per test-plan.md's Revision note) declares Tests/, *Tests/ and
    *Spec.cpp cpp layouts through the test_conventions: manifest key. The
    Tests/*Tests directory signal is recognised under BOTH tables (the
    built-in cpp table already covers a generic *Tests directory convention,
    matching AC-2's Source/AppTests/Foo.cpp case); the *Spec.cpp basename is
    the profile-specific extension and is recognised ONLY under the
    profile-extended table, so the anti-vacuity half of this assertion cannot
    pass under builtin_table() alone."""
    import yaml  # dev/test dependency only — imported lazily, see the sibling
    # test above for why
    manifest = yaml.safe_load(
        (_FIXTURES / "klc109-engine-profile" / "manifest.yml").read_text(encoding="utf-8"))
    table = tc.table_from_manifest(manifest)
    assert tc.is_test_path("Source/FooTests/Bar.cpp", table=table) is True
    # exists=lambda *_: True per the AC-2 amendment — FooSpec.cpp is a
    # basename-only match, so it needs a confirmed sibling like every other
    # such layout.
    assert tc.is_test_path("Source/Foo/Private/FooSpec.cpp", table=table,
                           exists=lambda *_: True) is True
    assert tc.is_test_path("Source/Foo/Private/FooSpec.cpp",
                           table=tc.builtin_table(), exists=lambda *_: True) is False


# ---------------------------------------------------------------------------
# Review-fix round 2 (D-109-9, supersedes D-109-7, code-review HIGH #1 +
# HIGH #2): a NAME-signal basename match OUTSIDE a declared test directory is
# trustworthy only when a caller supplies `exists=` AND the derived sibling
# production candidate is confirmed by it — closing the self-referential
# collision where test_conventions.py/test_map.py satisfy the bare python
# `test_*.py` glob with no sibling beside them. `root=` is GONE: every caller
# now supplies its own `exists=` (a git-tree probe for a gate, a universe-set
# membership check for an index builder — see the module docstring) instead
# of the live-filesystem `Path.exists()` HIGH #2 found unstable across time.
# ---------------------------------------------------------------------------

_REPO_ROOT = _file_dir.parent


def test_is_test_path_conservative_default_with_no_exists_no_io(monkeypatch):
    """AC-1/AC-6 (D-109-9): calling with NO `exists=` performs no filesystem
    I/O (poisoning Path.exists proves it: if the default path ever called
    it, this test would raise) AND returns the CONSERVATIVE answer — a
    basename-only match outside a declared test directory is NOT a test.
    This is what closes the self-referential collision even for a consumer
    that forgets to opt in at all (the round-1 default trusted the name
    signal unconditionally, which is exactly what let `test_map.py`/
    `test_conventions.py` misclassify themselves)."""
    def _boom(self, *a, **k):
        raise AssertionError("is_test_path() with no exists= must not touch the filesystem")

    monkeypatch.setattr(Path, "exists", _boom)
    assert tc.is_test_path("foo_test.go") is False
    assert tc.is_test_path("core/skills/test_map.py") is False
    assert tc.is_test_path("core/skills/test_conventions.py") is False
    # The directory signal and the 'sibling: none' layouts are UNAFFECTED —
    # they never consult `exists=` at all.
    assert tc.is_test_path("tests/test_x.py") is True
    assert tc.is_test_path("conftest.py") is True


def test_is_test_path_false_for_shared_modules_own_basename_against_real_repo_tree():
    """AC-6 review-fix (D-109-9): core/skills/test_map.py and
    core/skills/test_conventions.py are NOT tests once the caller opts in
    with a real, repo-backed `exists=` — no sibling map.py/conventions.py
    exists beside either file. This is the exact HIGH finding's regression
    case, now proven through `exists=`, not `root=`."""
    universe = {str(p.relative_to(_REPO_ROOT)).replace("\\", "/")
               for p in _REPO_ROOT.rglob("*.py") if p.is_file()}
    assert tc.is_test_path("core/skills/test_map.py",
                           exists=universe.__contains__) is False
    assert tc.is_test_path("core/skills/test_conventions.py",
                           exists=universe.__contains__) is False


def test_is_test_path_true_for_named_layout_with_existing_sibling_go(tmp_path):
    """AC-6 review-fix positive twin: pkg/foo_test.go IS a test once
    pkg/foo.go exists beside it, confirmed via `exists=`."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "foo.go").write_text("package pkg\n", encoding="utf-8")
    (pkg / "foo_test.go").write_text("package pkg\n", encoding="utf-8")
    assert tc.is_test_path("pkg/foo_test.go",
                           exists=lambda p: (tmp_path / p).exists()) is True


def test_is_test_path_true_for_named_layout_with_existing_sibling_ts(tmp_path):
    """AC-6 review-fix positive twin: src/x.test.ts IS a test once src/x.ts
    exists beside it, confirmed via `exists=`."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.ts").write_text("export {}\n", encoding="utf-8")
    (src / "x.test.ts").write_text("test('x', () => {})\n", encoding="utf-8")
    assert tc.is_test_path("src/x.test.ts",
                           exists=lambda p: (tmp_path / p).exists()) is True


def test_is_test_path_true_for_named_layout_with_existing_sibling_ruby(tmp_path):
    """AC-6 review-fix positive twin: lib/foo_spec.rb IS a test once
    lib/foo.rb exists beside it, confirmed via `exists=`."""
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "foo.rb").write_text("class Foo; end\n", encoding="utf-8")
    (lib / "foo_spec.rb").write_text("RSpec.describe Foo\n", encoding="utf-8")
    assert tc.is_test_path("lib/foo_spec.rb",
                           exists=lambda p: (tmp_path / p).exists()) is True


def test_is_test_path_false_for_named_layout_without_sibling_go(tmp_path):
    """AC-6 review-fix negative twin — the intended conservative behaviour:
    src/foo_test.go WITHOUT src/foo.go beside it is not a test even once the
    caller supplies a real `exists=`."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo_test.go").write_text("package src\n", encoding="utf-8")
    assert tc.is_test_path("src/foo_test.go",
                           exists=lambda p: (tmp_path / p).exists()) is False


def test_is_test_path_true_under_test_dir_regardless_of_sibling(tmp_path):
    """AC-6 review-fix: the directory rule is UNCHANGED — anything under a
    declared test directory is a test whether or not any sibling exists,
    even for an extension no LangRules record owns, and even with no
    `exists=` supplied at all."""
    assert tc.is_test_path("tests/anything.yml") is True


def test_is_test_path_true_for_sibling_none_conventions_with_no_exists():
    """AC-6 review-fix: a basename convention with no derivable stem
    (conftest.py, tests.rs, test.rs — the file IS the whole test artefact,
    'sibling: none') stays a test even with NO `exists=` supplied at all —
    there is no sibling to confirm, so the conservative default never
    applies to this bucket."""
    assert tc.is_test_path("conftest.py") is True
    assert tc.is_test_path("tests.rs") is True
    assert tc.is_test_path("test.rs") is True


def test_is_test_path_sibling_check_uses_injected_exists_predicate():
    """AC-6 review-fix: the `exists=` seam receives the derived sibling
    CANDIDATE STRING directly (no `root=` join happens inside the module any
    more) — proving the seam is the caller's own responsibility to resolve
    against a git tree, a universe set or anything else."""
    seen: list[str] = []

    def _fake_exists(cand: str) -> bool:
        seen.append(cand)
        return cand.endswith("foo.go")

    assert tc.is_test_path("pkg/foo_test.go", exists=_fake_exists) is True
    assert seen == ["pkg/foo.go"], seen


# ---------------------------------------------------------------------------
# Review-fix round 2 (D-109-9, code-review HIGH #1): the js/ts LangRules
# row's prod_exts now covers every js/ts test extension (was: only .ts/.tsx),
# so a plain-JavaScript colocated test can derive and confirm its OWN
# extension as a sibling, table-driven per language row — not a per-file
# carve-out.
# ---------------------------------------------------------------------------

JS_SIBLING_LAYOUTS = [
    ("Foo.spec.js", "Foo.js"),
    ("Foo.test.jsx", "Foo.jsx"),
    ("x.test.mjs", "x.mjs"),
    ("x.test.cjs", "x.cjs"),
    ("x.test.tsx", "x.tsx"),
]


@pytest.mark.parametrize("test_path,prod_path", JS_SIBLING_LAYOUTS)
def test_is_test_path_true_for_js_family_sibling_own_extension(tmp_path, test_path, prod_path):
    """AC-6/HIGH #1: a plain-JavaScript (or mjs/cjs) colocated test pairs
    with its OWN extension's production sibling — the row's prod_exts is no
    longer restricted to .ts/.tsx, so Foo.spec.js beside Foo.js is
    recognised exactly like Foo.test.tsx beside Foo.tsx."""
    (tmp_path / prod_path).write_text("// prod\n", encoding="utf-8")
    (tmp_path / test_path).write_text("test('x', () => {});\n", encoding="utf-8")
    assert tc.is_test_path(test_path, exists=lambda p: (tmp_path / p).exists()) is True


def test_is_test_path_false_for_plain_js_colocated_test_without_sibling_honest_history(tmp_path):
    """HIGH #1 end-to-end repro: BEFORE its sibling exists, a plain-JS test
    file (Foo.spec.js with no Foo.js anywhere) is NOT confirmed a test under
    a real `exists=` — the honest RED state of a colocated-test project. Once
    Foo.js is added, the SAME path (unchanged) IS confirmed."""
    (tmp_path / "Foo.spec.js").write_text("test('x', () => {});\n", encoding="utf-8")
    exists = lambda p: (tmp_path / p).exists()  # noqa: E731
    assert tc.is_test_path("Foo.spec.js", exists=exists) is False
    (tmp_path / "Foo.js").write_text("module.exports = {};\n", encoding="utf-8")
    assert tc.is_test_path("Foo.spec.js", exists=exists) is True


def test_is_test_path_true_for_ts_test_confirmed_by_plain_js_sibling():
    """Review round 3 LOW: the js/ts row's `prod_exts` widening (round 2,
    D-109-9, HIGH #1) is shared across every extension in the row, so a
    `.ts`/`.tsx` test file can be confirmed a test purely by a same-stem
    `.js`/`.jsx`/`.mjs`/`.cjs` production sibling, with NO TypeScript file
    present anywhere. This pins the behaviour down as deliberate policy (a
    TypeScript/JavaScript migration project mixes extensions file-by-file),
    not an unconsidered side effect of grouping the whole family into one
    LangRules row — see the row's own comment in `BUILTIN`."""
    assert tc.is_test_path("foo.spec.ts", exists=lambda p: p == "foo.js") is True
    assert tc.is_test_path("foo.spec.ts", exists=lambda p: False) is False


def test_production_candidates_unaffected_by_exists_gate_jsts():
    """AC-4: production_candidates keeps answering the pattern-shape question
    with NO existence gate at all (D-109-9 explicitly keeps this function on
    `_shape_signal`, never `test_signal`) — widening prod_exts only ADDS
    candidates after the test file's own extension, it never removes the
    TypeScript pairing AC-4 already asserts."""
    cands = tc.production_candidates("Foo.spec.js")
    assert cands[0] == "Foo.js"
    cands2 = tc.production_candidates("x.test.mjs")
    assert cands2[0] == "x.mjs"


# ---------------------------------------------------------------------------
# Review-fix round 4 (D-109-12, supersedes D-109-10, code-review HIGH round
# 3): a caller may also pass `added=`, a str -> bool predicate telling
# whether the classified path itself is newly introduced. A freshly-added
# basename-shaped match needs no confirmed sibling; a pre-existing one still
# does. `added=None` (the default) disables the rule outright.
# ---------------------------------------------------------------------------

def test_is_test_path_true_when_added_true_and_no_sibling_confirmed():
    """AC-6, D-109-12: a freshly-added basename match (added(path) is True)
    is a test even with exists=None and no sibling anywhere — the mid-step
    RED-only window this round-4 fix exists to stop falsely sanctioning."""
    assert tc.is_test_path("pkg/foo_test.go", added=lambda p: True) is True
    assert tc.is_test_path("pkg/foo_test.go", exists=lambda p: False,
                           added=lambda p: True) is True


def test_is_test_path_false_when_added_false_and_no_sibling_confirmed():
    """D-109-12: a PRE-EXISTING basename match (added(path) is False) still
    needs a confirmed sibling — the new-file rule never widens the
    conservative default for a path that already existed before this
    commit/diff."""
    assert tc.is_test_path("pkg/foo_test.go", added=lambda p: False) is False
    assert tc.is_test_path("pkg/foo_test.go", exists=lambda p: False,
                           added=lambda p: False) is False


def test_is_test_path_added_true_does_not_override_sibling_none_or_dir_signal():
    """D-109-12: `added=` only ever matters for the NAME signal's sibling
    check — it must not change the 'sibling: none' bucket (already always
    True) or the directory signal (already unconditional and never gated on
    exists=/added= at all)."""
    assert tc.is_test_path("conftest.py", added=lambda p: False) is True
    assert tc.is_test_path("tests/foo.py", added=lambda p: False) is True


def test_is_test_path_added_none_default_matches_round_2_behaviour():
    """D-109-12: `added=None` (the default — no caller passes it) behaves
    identically to round 2 (D-109-9): a pre-existing-or-unknown basename
    match with no confirmed sibling is NOT a test, and the conservative
    no-`exists=`-at-all default is also unaffected."""
    assert tc.is_test_path("pkg/foo_test.go") is False
    assert tc.is_test_path("pkg/foo_test.go", exists=lambda p: False) is False
    assert tc.is_test_path("pkg/foo_test.go", exists=lambda p: p == "pkg/foo.go") is True


def test_is_test_path_added_called_with_the_classified_path_not_the_sibling():
    """D-109-12: `added` is consulted with the PATH BEING CLASSIFIED, never
    a derived sibling candidate — the two predicates answer different
    questions about different strings."""
    seen: list[str] = []

    def _added(p: str) -> bool:
        seen.append(p)
        return True

    assert tc.is_test_path("pkg/foo_test.go", added=_added) is True
    assert seen == ["pkg/foo_test.go"], seen
