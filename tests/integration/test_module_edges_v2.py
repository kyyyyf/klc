"""KLC-070 step-3 — module_edges.json v2 (evidence-count ranking)."""
import inspect
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import module_edges as me  # noqa: E402

_MODULES = {"modules": [
    {"name": "intake", "path": "core/intake/"},
    {"name": "routing", "path": "core/routing/"},
    {"name": "billing", "path": "core/billing/"},
]}


def test_aggregate_signature_preserved():
    """AC-6: the library API imported by init/update is unchanged."""
    sig = inspect.signature(me.aggregate_module_edges)
    assert list(sig.parameters) == ["modules_data", "depgraph"]


def test_evidence_count_by_distinct_class():
    """AC-7: evidence_count is the number of distinct (source,type) classes.

    intake→routing has 10 import edges (ONE class) + 1 call (second class) + 1 test
    import (third class). billing→routing has a single import edge from a generated
    file (ONE class). The three-class edge must outrank the one-class edge.
    """
    edges_10 = [{"from": f"core/intake/f{i}.py", "to": "core/routing/router.py"}
                for i in range(10)]
    depgraph = {"import_graphs": {"python": {"edges": edges_10 + [
        {"from": "tests/test_intake.py", "to": "core/routing/router.py"},   # test_import
        {"from": "core/billing/gen.py", "to": "core/routing/router.py"},    # 1 class
    ]}}}
    callgraph = {"symbols": {"core/routing/router.py::route": {
        "file": "core/routing/router.py",
        "called_by": ["core/intake/validation.py::run"]}}}   # call class

    # NOTE: tests/test_intake.py resolves to no module here → its evidence is dropped
    # unless a tests module exists. Add one so the test_import class counts.
    modules = {"modules": _MODULES["modules"] + [{"name": "tests", "path": "tests/"}]}
    out = me.build_detailed_edges(modules, depgraph, callgraph)
    by_pair = {(e["from"], e["to"]): e for e in out["edges"]}

    ir = by_pair[("intake", "routing")]
    # classes: (import_graph, runtime_import) + (callgraph, call) = 2 distinct.
    assert ir["evidence_count"] == 2
    assert set(ir["edge_types"]) == {"runtime_import", "call"}
    assert ir["confidence"] == "medium"

    br = by_pair[("billing", "routing")]
    assert br["evidence_count"] == 1          # 10-vs-1 raw count must NOT decide
    assert br["confidence"] == "low"

    # The richer edge ranks first (sorted by -evidence_count).
    assert out["edges"][0]["evidence_count"] >= out["edges"][-1]["evidence_count"]
    assert ir["evidence_count"] > br["evidence_count"]


def test_llm_evidence_excluded_from_rank():
    """AC-7: an LLM/decompose hint lands in advisory_reason, never in the count."""
    depgraph = {"import_graphs": {"python": {"edges": [
        {"from": "core/intake/a.py", "to": "core/routing/r.py"},
    ]}}}
    advisory = {("intake", "routing"): "decompose (LLM): ValidationResult consumed"}
    out = me.build_detailed_edges(_MODULES, depgraph, None, advisory=advisory)
    edge = out["edges"][0]
    assert edge["advisory_reason"].startswith("decompose (LLM)")
    assert edge["evidence_count"] == 1   # advisory did not bump the count
    # advisory reason is not a piece of counted evidence.
    assert all("decompose" not in ev.get("source", "") for ev in edge["evidence"])

    # A decompose-only pair (no deterministic file edge) yields NO edge at all.
    out2 = me.build_detailed_edges(
        _MODULES, {"import_graphs": {}}, None,
        advisory={("intake", "billing"): "LLM guess"})
    assert out2["edges"] == []


def test_out_edges_and_modules_both_written(tmp_path):
    """AC-6: main() writes coarse depends_on into modules.json AND detailed edges."""
    modules_file = tmp_path / "modules.json"
    modules_file.write_text(json.dumps(_MODULES), encoding="utf-8")
    depgraph_file = tmp_path / "depgraph.json"
    depgraph_file.write_text(json.dumps({"import_graphs": {"python": {"edges": [
        {"from": "core/intake/a.py", "to": "core/routing/r.py"},
    ]}}}), encoding="utf-8")
    out_edges = tmp_path / "module_edges.json"

    rc = me.main([
        "--in-modules", str(modules_file), "--in-depgraph", str(depgraph_file),
        "--in-callgraph-dir", str(tmp_path / "nocg"),
        "--out-modules", str(modules_file), "--out-edges", str(out_edges),
    ])
    assert rc == 0

    # coarse edges back in modules.json
    mods = json.loads(modules_file.read_text(encoding="utf-8"))
    intake = next(m for m in mods["modules"] if m["name"] == "intake")
    assert "routing" in intake["depends_on"]
    # detailed edges in the separate file
    detailed = json.loads(out_edges.read_text(encoding="utf-8"))
    assert detailed["edges"][0]["from"] == "intake"
    assert detailed["edges"][0]["to"] == "routing"
    assert "generated_at" in detailed  # top-level only


def test_nonpython_callgraph_contributes_call_class():
    """FIX-3: a non-python callgraph (rust/cpp) still yields a 'call' edge class."""
    depgraph = {"import_graphs": {}}
    cpp_cg = {"symbols": {"core/routing/r.cpp::route": {
        "file": "core/routing/r.cpp",
        "called_by": ["core/intake/a.cpp::Handle"]}}}
    out = me.build_detailed_edges(_MODULES, depgraph, cpp_cg)
    edge = next(e for e in out["edges"] if e["from"] == "intake" and e["to"] == "routing")
    assert "call" in edge["edge_types"]
    assert edge["evidence_count"] == 1


def test_load_callgraph_dir_merges_languages(tmp_path):
    """FIX-3: the loader merges rust.json / cpp.json (no python.json)."""
    cg = tmp_path / "callgraph"
    cg.mkdir()
    (cg / "rust.json").write_text(json.dumps(
        {"symbols": {"a::x": {"file": "a", "called_by": []}}}), encoding="utf-8")
    (cg / "cpp.json").write_text(json.dumps(
        {"symbols": {"b::y": {"file": "b", "called_by": []}}}), encoding="utf-8")
    merged = me._load_callgraph_dir(cg)
    assert set(merged["symbols"]) == {"a::x", "b::y"}


def test_edges_only_does_not_touch_modules(tmp_path):
    """FIX-4: --edges-only writes module_edges.json but leaves modules.json byte-identical."""
    modules_file = tmp_path / "modules.json"
    original = json.dumps(_MODULES)
    modules_file.write_text(original, encoding="utf-8")
    depgraph_file = tmp_path / "depgraph.json"
    depgraph_file.write_text(json.dumps({"import_graphs": {"python": {"edges": [
        {"from": "core/intake/a.py", "to": "core/routing/r.py"},
    ]}}}), encoding="utf-8")
    out_edges = tmp_path / "module_edges.json"

    rc = me.main([
        "--edges-only",
        "--in-modules", str(modules_file), "--in-depgraph", str(depgraph_file),
        "--in-callgraph-dir", str(tmp_path / "nocg"),
        "--out-modules", str(modules_file), "--out-edges", str(out_edges),
    ])
    assert rc == 0
    # modules.json untouched — NOT re-aggregated (no depends_on added).
    assert modules_file.read_text(encoding="utf-8") == original
    after = json.loads(modules_file.read_text(encoding="utf-8"))
    assert "depends_on" not in after["modules"][0]
    # but detailed edges were written.
    assert json.loads(out_edges.read_text(encoding="utf-8"))["edges"]


def test_missing_modules_exit2(tmp_path):
    rc = me.main(["--in-modules", str(tmp_path / "absent.json"),
                  "--out-edges", str(tmp_path / "e.json")])
    assert rc == 2


def test_determinism():
    """AC-11: byte-identical on re-run; no inner timestamp."""
    depgraph = {"import_graphs": {"python": {"edges": [
        {"from": "core/intake/a.py", "to": "core/routing/r.py"},
    ]}}}
    a = me.build_detailed_edges(_MODULES, depgraph, None)
    b = me.build_detailed_edges(_MODULES, depgraph, None)
    assert json.dumps(a) == json.dumps(b)
    assert "generated_at" not in a
