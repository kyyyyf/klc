"""tests/integration/test_klc109_fixtures.py — KLC-109 step-8, AC-13: one
red→green fixture repository per language layout proves the ordering gate
passes on a correct history and that test_map finds the suite with no
callgraph and no import graph.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import tdd_order as td  # noqa: E402
import test_map as tm  # noqa: E402

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_LAYOUTS = ["python", "js-ts", "go", "rust", "java-kotlin", "csharp", "ruby", "cpp"]


@pytest.mark.parametrize("layout", _LAYOUTS)
def test_ordering_gate_passes_on_each_language_fixture_repo(klc109_repo, layout):
    """AC-13: verify_step returns ok=True on the shipped red→green history for
    every one of the eight named language layouts."""
    repo = klc109_repo(layout)
    ok, reason = td.verify_step("KLC-109F", 1, repo)
    assert ok, f"{layout}: {reason}"


@pytest.mark.parametrize("layout", _LAYOUTS)
def test_test_map_finds_suite_on_each_language_fixture_with_no_graphs(klc109_repo, layout):
    """AC-13: build_test_map, fed the fixture's own files_rel/root and NO
    depgraph/callgraph, still finds the suite via the convention layer."""
    repo = klc109_repo(layout)
    plan = json.loads((_FIXTURES / f"klc109-{layout}" / "history.json").read_text(encoding="utf-8"))
    files_rel = sorted(plan["red"] + plan["green"])
    structural = {"files_rel": files_rel, "root": str(repo)}
    result = tm.build_test_map(structural, {}, {}, None)
    prod = plan["green"][0]
    test = plan["red"][0]
    entry = result["production_to_tests"].get(prod)
    assert entry is not None, (layout, result)
    assert any(r["test_file"] == test for r in entry["tests"]), (layout, entry)
