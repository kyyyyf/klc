"""KLC-024 step-2: deterministic module reverse-edge aggregation."""
import json
import sys
from pathlib import Path

import pytest

_skills = Path(__file__).parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(_skills))
import module_edges as _me  # noqa: E402


def _modules(entries):
    return {"modules": entries}


def _depgraph(edges, lang="python"):
    return {
        "import_graphs": {
            lang: {"edges": [{"from": e[0], "to": e[1]} for e in edges]}
        }
    }


MOD_A = {"name": "modA", "path": "src/a", "files": ["src/a/foo.py"], "depends_on": [], "depended_by": []}
MOD_B = {"name": "modB", "path": "src/b", "files": ["src/b/bar.py"], "depends_on": [], "depended_by": []}
MOD_C = {"name": "modC", "path": "src/c", "files": ["src/c/baz.py"], "depends_on": [], "depended_by": []}


def test_reverse_edges_populated():
    """modules get non-empty depends_on/depended_by after aggregation."""
    mods = _modules([dict(MOD_A), dict(MOD_B)])
    graph = _depgraph([("src/b/bar.py", "src/a/foo.py")])  # B imports A
    result = _me.aggregate_module_edges(mods, graph)
    by_name = {m["name"]: m for m in result["modules"]}
    assert by_name["modB"]["depends_on"] != []
    assert by_name["modA"]["depended_by"] != []


def test_reverse_edge_correct():
    """B imports A → A.depended_by=[modB], B.depends_on=[modA]."""
    mods = _modules([dict(MOD_A), dict(MOD_B)])
    graph = _depgraph([("src/b/bar.py", "src/a/foo.py")])  # B→A
    result = _me.aggregate_module_edges(mods, graph)
    by_name = {m["name"]: m for m in result["modules"]}
    assert by_name["modA"]["depended_by"] == ["modB"]
    assert by_name["modB"]["depends_on"] == ["modA"]


def test_self_edge_skipped():
    """File edge within same module must NOT create a self-dependency."""
    mods = _modules([dict(MOD_A)])
    graph = _depgraph([("src/a/foo.py", "src/a/bar.py")])  # intra-module
    result = _me.aggregate_module_edges(mods, graph)
    m = result["modules"][0]
    assert m["depends_on"] == []
    assert m["depended_by"] == []


def test_unmapped_endpoint_skipped():
    """Edge endpoint outside all module paths is skipped, no crash."""
    mods = _modules([dict(MOD_A)])
    graph = _depgraph([("vendor/x.py", "src/a/foo.py")])  # from=unmapped
    result = _me.aggregate_module_edges(mods, graph)
    m = result["modules"][0]
    assert m["depended_by"] == []


def test_no_depgraph_noop():
    """Missing depgraph or empty import_graphs → no crash, empty edges."""
    mods = _modules([dict(MOD_A), dict(MOD_B)])
    result = _me.aggregate_module_edges(mods, {})
    by_name = {m["name"]: m for m in result["modules"]}
    assert by_name["modA"]["depends_on"] == []
    assert by_name["modA"]["depended_by"] == []


def test_deduplication():
    """Multiple file edges between same module pair produce single entry."""
    mods = _modules([dict(MOD_A), dict(MOD_B)])
    graph = _depgraph([
        ("src/b/bar.py", "src/a/foo.py"),
        ("src/b/bar.py", "src/a/foo.py"),  # duplicate
    ])
    result = _me.aggregate_module_edges(mods, graph)
    by_name = {m["name"]: m for m in result["modules"]}
    assert by_name["modA"]["depended_by"] == ["modB"]
    assert by_name["modB"]["depends_on"] == ["modA"]
