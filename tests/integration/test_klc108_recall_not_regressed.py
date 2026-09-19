"""KLC-108 — AC-5: the per-language coverage property KLC-103 established
still holds after the top-level restriction. Extends
`tests/integration/test_klc103_rule_coverage.py`'s corpus with the KLC-108
scope fixtures (each of which ALSO declares in-body locals alongside its
top-level export) — the count of fixture files that declare a top-level
export and yield zero symbols must remain 0 for every configured language.

Real substrate: the REAL merged ruleset (active profile) through the REAL
production scan path (`deterministic_inventory.build_inventory`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
FIXTURES_ROOT = REPO_ROOT / "tests" / "fixtures" / "rules"
TS_FIXTURES = FIXTURES_ROOT / "typescript"
COV_FIXTURES = FIXTURES_ROOT / "coverage"
PY_FIXTURES = FIXTURES_ROOT / "python"
RUST_FIXTURES = FIXTURES_ROOT / "rust"
CPP_FIXTURES = FIXTURES_ROOT / "cpp"

sys.path.insert(0, str(SKILLS))
import deterministic_inventory as di  # noqa: E402
import tools  # noqa: E402


def _astgrep_or_skip() -> str:
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


# (case id, fixture root, fixture filename) — the KLC-103 floor plus every
# KLC-108 scope fixture (each ALSO carries an in-body local beside its
# top-level export/pub/class declaration).
_CASES = [
    ("typescript/.ts", TS_FIXTURES, "sample.ts"),
    ("typescript-scope/.ts", TS_FIXTURES, "scope.ts"),
    ("tsx/.tsx", TS_FIXTURES, "sample.tsx"),
    ("tsx-scope/.tsx", TS_FIXTURES, "scope.tsx"),
    ("javascript/.js", TS_FIXTURES, "sample.js"),
    ("javascript-scope/.js", TS_FIXTURES, "scope.js"),
    ("python/.py", COV_FIXTURES, "sample.py"),
    ("python-scope/.py", PY_FIXTURES, "scope.py"),
    ("rust/.rs", COV_FIXTURES, "sample.rs"),
    ("rust-scope/.rs", RUST_FIXTURES, "scope.rs"),
    ("cpp/.cpp", COV_FIXTURES, "sample.cpp"),
    ("cpp-scope/.cpp", CPP_FIXTURES, "scope.cpp"),
    ("cpp-header/.h", COV_FIXTURES, "sample.h"),
    ("cpp-header-scope/.h", CPP_FIXTURES, "scope.h"),
]


@pytest.mark.parametrize("case_id,root,filename",
                        _CASES, ids=[c[0] for c in _CASES])
def test_every_language_exporting_fixture_still_yields_at_least_one_symbol(
        case_id, root, filename):
    """AC-5: after the top-level restriction, the count of fixture files
    that declare a top-level export and yield zero symbols is 0 — for
    every language the active (generic) profile configures."""
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(root, ruleset, astgrep, files=[filename])
    assert inv["errors"] == [], f"{case_id}: scan degraded: {inv['errors']}"
    symbols = [s for s in inv["symbols"] if s["file"] == filename]
    assert symbols, (
        f"{case_id}: fixture {filename} declares a top-level export but "
        f"yielded 0 symbols after the KLC-108 scope restriction")
    assert all(s["source_of_truth"] == "ast_grep" for s in symbols), (
        f"{case_id}: expected ast-grep source_of_truth, not a regex-fallback "
        f"symbol — {symbols}")
