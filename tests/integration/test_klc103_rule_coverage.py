"""KLC-103 — AC-1: each configured language rule set captures at least one
symbol from every fixture file that declares a top-level export, across
every file extension the active profile maps to that language.

Real substrate: the REAL merged ruleset (active profile) through the REAL
production scan path (`deterministic_inventory.build_inventory`)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
TS_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "rules" / "typescript"
COV_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "rules" / "coverage"

sys.path.insert(0, str(SKILLS))
import deterministic_inventory as di  # noqa: E402
import tools  # noqa: E402


def _astgrep_or_skip() -> str:
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


# (case id, fixture root, fixture filename)
_CASES = [
    ("typescript/.ts", TS_FIXTURES, "sample.ts"),
    ("tsx/.tsx", TS_FIXTURES, "sample.tsx"),
    ("javascript/.js", TS_FIXTURES, "sample.js"),
    ("python/.py", COV_FIXTURES, "sample.py"),
    ("rust/.rs", COV_FIXTURES, "sample.rs"),
    ("cpp/.cpp", COV_FIXTURES, "sample.cpp"),
    ("cpp-unreal/.h", COV_FIXTURES, "sample_unreal.h"),
]


@pytest.mark.parametrize("case_id,root,filename",
                        _CASES, ids=[c[0] for c in _CASES])
def test_rule_coverage_floor_per_language(case_id, root, filename):
    """AC-1: the count of fixture files that declare an export and yield
    zero symbols is 0 — for every language the active (UE) profile
    configures, across every file extension it maps to that language."""
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(root, ruleset, astgrep, files=[filename])
    assert inv["errors"] == [], f"{case_id}: scan degraded: {inv['errors']}"
    symbols = [s for s in inv["symbols"] if s["file"] == filename]
    assert symbols, (
        f"{case_id}: fixture {filename} declares a top-level export but "
        f"yielded 0 symbols")
    assert all(s["source_of_truth"] == "ast_grep" for s in symbols), (
        f"{case_id}: expected ast-grep source_of_truth, not a regex-fallback "
        f"symbol — {symbols}")
