"""KLC-103 — AC-3: the declared `tests:` cases of every rule file under
`core/rules` and `profiles/*/rules` are executed through the production
scan path, not decorative (spec.md F-101: `ast-grep test` reports "Running 0
tests" over the shipped rule directory today)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TESTS_ROOT = REPO_ROOT / "tests"
SYNTHETIC = TESTS_ROOT / "fixtures" / "rules" / "synthetic"

sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "skills"))

from rule_test_executor import run_rule_tests  # noqa: E402


def _astgrep_or_skip():
    import tools
    if not tools.resolve_tool("ast-grep"):
        pytest.skip("ast-grep not installed in this environment")


def _active_profile_language_globs() -> dict:
    import deterministic_inventory as di
    return di.resolve_ruleset().get("language_globs") or {}


def test_executor_runs_declared_cases_for_every_rule_file():
    """AC-3 / AC-12: the real executor walks `core/rules/*` +
    `profiles/*/rules` and runs each file's declared `tests:` block through
    a real ast-grep scan. Zero failures — every shipped rule file's
    declarations are true (F-104's four failing cases and four case-less
    files are all fixed by this step)."""
    _astgrep_or_skip()
    rule_dirs = [
        REPO_ROOT / "core" / "rules" / "typescript",
        REPO_ROOT / "core" / "rules" / "python",
        REPO_ROOT / "core" / "rules" / "rust",
        REPO_ROOT / "core" / "rules" / "cpp",
        REPO_ROOT / "profiles" / "ue" / "rules" / "cpp-unreal",
    ]
    failures = run_rule_tests(rule_dirs, _active_profile_language_globs())
    assert failures == [], "\n".join(failures)


def test_executor_fails_on_rule_with_no_test_cases():
    """Negative twin 1/3: a rule file with no `tests:` key at all must fail
    the gate."""
    _astgrep_or_skip()
    failures = run_rule_tests([SYNTHETIC], {})
    assert any("no-cases.yaml" in f and "no test cases" in f for f in failures), failures


def test_executor_fails_on_valid_case_with_no_match():
    """Negative twin 2/3: a `valid` case that does not match its own pattern
    must fail the gate."""
    _astgrep_or_skip()
    failures = run_rule_tests([SYNTHETIC], {})
    assert any("valid-no-match.yaml" in f and "valid #0" in f and "no match" in f
               for f in failures), failures


def test_executor_fails_on_invalid_case_that_matches():
    """Negative twin 3/3: an `invalid` case that DOES match must fail the
    gate."""
    _astgrep_or_skip()
    failures = run_rule_tests([SYNTHETIC], {})
    assert any("invalid-matches.yaml" in f and "invalid #0" in f and "matched" in f
               for f in failures), failures
