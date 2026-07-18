"""KLC-070 step-2 — test_map.json production↔tests builder."""
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import test_map as tm  # noqa: E402

_MODULES = {"modules": [
    {"name": "pkg", "path": "pkg/"},
    {"name": "solo", "path": "solo/"},
    {"name": "cg", "path": "cg/"},
]}

_DEPGRAPH = {"import_graphs": {"python": {
    "nodes": [
        {"id": "pkg/mod.py"}, {"id": "pkg/other.py"}, {"id": "pkg/test_inline.py"},
        {"id": "tests/test_mod.py"}, {"id": "solo/thing.py"}, {"id": "cg/target.py"},
    ],
    "edges": [
        {"from": "tests/test_mod.py", "to": "pkg/mod.py"},   # direct_import
    ],
}}}

# cg/target.py::do is called by a test symbol → 'call' relationship.
_CALLGRAPH = {"symbols": {
    "cg/target.py::do": {"kind": "function", "file": "cg/target.py",
                         "called_by": ["tests/test_mod.py::test_uses_do"]},
}}


def _build(callgraph=None):
    return tm.build_test_map({}, _DEPGRAPH, _MODULES, callgraph)


def test_production_to_tests_object_form():
    """AC-4: every production entry is the object form {coverage, tests[]}."""
    result = _build()
    p2t = result["production_to_tests"]
    assert "module_to_tests" in result
    for entry in p2t.values():
        assert set(entry) == {"coverage", "tests"}
        assert entry["coverage"] in {"direct", "module", "none"}
        assert isinstance(entry["tests"], list)
    # pkg/mod.py is directly imported by tests/test_mod.py.
    mod = p2t["pkg/mod.py"]
    assert mod["coverage"] == "direct"
    assert any(r["test_file"] == "tests/test_mod.py"
               and r["relationship"] == "direct_import" for r in mod["tests"])
    # module_to_tests groups the linked tests under the module.
    assert "tests/test_mod.py" in result["module_to_tests"]["pkg"]


def test_no_tests_records_coverage_none():
    """AC-4: an untested production file gets an explicit none record, not omission."""
    result = _build()
    solo = result["production_to_tests"]["solo/thing.py"]
    assert solo == {"coverage": "none", "tests": []}


def test_relationship_priority():
    """AC-4: direct_import outranks the weaker name_similarity for the same pair."""
    result = _build()
    rows = result["production_to_tests"]["pkg/mod.py"]["tests"]
    row = next(r for r in rows if r["test_file"] == "tests/test_mod.py")
    # tests/test_mod.py both imports pkg/mod.py AND name-matches its stem; the higher
    # signal must win.
    assert row["relationship"] == "direct_import"
    assert row["confidence"] == "high"


def test_call_relationship_from_callgraph():
    """AC-4/AC-8-substrate: a test that calls a prod symbol yields 'call' (high)."""
    with_cg = _build(_CALLGRAPH)
    target = with_cg["production_to_tests"]["cg/target.py"]
    assert target["coverage"] == "direct"
    assert target["tests"][0]["relationship"] == "call"

    # Degrade: without callgraph the same file has no 'call' link.
    without_cg = _build(None)
    assert without_cg["production_to_tests"]["cg/target.py"]["coverage"] == "none"


def test_same_module_is_module_level_not_per_file_row():
    """FIX-6: a file whose only association is a co-located test reports coverage:none
    (a visible hole); same_module lives in module_to_tests, not per-file rows, and the
    O(prod×test) cross-product never appears."""
    result = _build()
    other = result["production_to_tests"]["pkg/other.py"]
    # pkg/other.py has no direct/call/name link → a genuine hole stays visible.
    assert other["coverage"] == "none"
    assert other["tests"] == []
    # No production_to_tests row anywhere carries the module-level 'same_module' rel.
    for entry in result["production_to_tests"].values():
        assert all(r["relationship"] != "same_module" for r in entry["tests"])
    # But the co-located test still surfaces at module level.
    assert "pkg/test_inline.py" in result["module_to_tests"]["pkg"]


def test_multilang_callgraph_call_links():
    """FIX-2: call links must work when the callgraph is rust.json / cpp.json (no
    python.json). load_callgraph_dir merges every language present."""
    from pathlib import Path as _P
    import tempfile
    modules = {"modules": [{"name": "cg", "path": "cg/"}]}
    depgraph = {"import_graphs": {"cpp": {
        "nodes": [{"id": "cg/target.cpp"}, {"id": "tests/test_target.cpp"}],
        "edges": [],
    }}}
    rust_cg = {"symbols": {"cg/target.cpp::do": {
        "file": "cg/target.cpp",
        "called_by": ["tests/test_target.cpp::TestDo"]}}}

    with tempfile.TemporaryDirectory() as d:
        cg_dir = _P(d) / "callgraph"
        cg_dir.mkdir()
        (cg_dir / "rust.json").write_text(json.dumps(rust_cg), encoding="utf-8")
        merged = tm.load_callgraph_dir(cg_dir)
    assert merged is not None and "cg/target.cpp::do" in merged["symbols"]

    result = tm.build_test_map({}, depgraph, modules, merged)
    target = result["production_to_tests"]["cg/target.cpp"]
    assert target["coverage"] == "direct"
    assert target["tests"][0]["relationship"] == "call"


def test_determinism(tmp_path):
    """AC-11: byte-identical on re-run; no inner timestamp."""
    a = _build(_CALLGRAPH)
    b = _build(_CALLGRAPH)
    assert json.dumps(a) == json.dumps(b)
    assert "generated_at" not in a
