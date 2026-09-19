"""KLC-106 step-3 — every import-graph producer is measured, the richer
candidate wins, madge gets its flags (AC-4, AC-5, AC-6).

`dep_graph.py` already threads a KLC-105 file universe through every producer
to post-filter its raw tool output; this ticket layers a coverage VERDICT on
top of that plumbing. Producers whose nodes are not files at all (cargo
metadata, cmake --graphviz, the UE *.Build.cs walk) have no natural file
denominator (Q-005/D-002) and always record `metric: "not-applicable"`,
`degraded: false` — never a fabricated ratio.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_skills = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
if str(_skills) not in sys.path:
    sys.path.insert(0, str(_skills))

import dep_graph  # noqa: E402


def _structural(root: Path, languages: dict, total_files: int) -> None:
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "structural.json").write_text(json.dumps({
        "root": str(root), "total_files": total_files, "languages": languages,
    }), encoding="utf-8")


def _no_op_packages(monkeypatch):
    monkeypatch.setattr(dep_graph, "_python_package_graph", lambda root: (None, []))
    monkeypatch.setattr(dep_graph, "_rust_package_graph", lambda root: (None, []))
    monkeypatch.setattr(dep_graph, "_cpp_package_graph", lambda root: (None, []))


def _resolve_stub(monkeypatch, *, discovery_mode="", collect_packages=False, tsconfig=""):
    def fake_resolve(field):
        if field == "module_discovery":
            return json.dumps({"mode": discovery_mode}) if discovery_mode else "{}"
        if field == "collect_package_graphs":
            return "true" if collect_packages else "false"
        if field == "tsconfig":
            return tsconfig
        return ""
    monkeypatch.setattr(dep_graph, "_resolve", fake_resolve)


def _node(path):
    return {"id": path, "path": path}


def _graph(tool, nodes, edges=()):
    return {"tool": tool, "nodes": [_node(n) for n in nodes],
            "edges": [{"from": a, "to": b} for a, b in edges], "raw": None}


# --------------------------------------------------------------------- AC-4

def test_each_import_graph_producer_stamps_degraded_below_threshold(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    _structural(root, {"python": {"files": 20}, "typescript": {"files": 20},
                        "cpp": {"files": 5}}, total_files=25)
    _resolve_stub(monkeypatch, discovery_mode="build-cs", collect_packages=True)

    # generic scanner: 1 of 20 python files -> below the 0.25 default floor.
    monkeypatch.setattr(dep_graph, "_import_graphs_from_scanner",
                         lambda root: ({"python": _graph("import-graph.py", ["a.py"])}, []))
    # madge: sole typescript candidate, 1 of 20 -> below floor too.
    monkeypatch.setattr(dep_graph, "_madge_typescript",
                         lambda root, universe: {**_graph("madge", ["a.ts"]), "errors": []})
    # cargo metadata / cmake / UE walk: no file denominator (D-002) regardless
    # of node count — must stay not-applicable, never a fabricated ratio.
    monkeypatch.setattr(dep_graph, "_rust_package_graph",
                         lambda root: (_graph("cargo metadata", ["pkgA"]), []))
    monkeypatch.setattr(dep_graph, "_python_package_graph", lambda root: (None, []))
    monkeypatch.setattr(dep_graph, "_cpp_package_graph",
                         lambda root: (_graph("cmake --graphviz", ["nodeA"]), []))
    monkeypatch.setattr(dep_graph, "_ue_import_graph",
                         lambda root, excl, universe: _graph("grep *.Build.cs", ["ModA"]))

    result = dep_graph.build(root)

    py = result["import_graphs"]["python"]
    assert py["degraded"] is True and py["reason"]
    ts = result["import_graphs"]["typescript"]
    assert ts["degraded"] is True and ts["reason"]
    rust_pkg = result["package_graphs"]["rust"]
    assert rust_pkg["degraded"] is False and rust_pkg.get("metric", dep_graph.index_coverage.NOT_APPLICABLE)
    cpp_pkg = result["package_graphs"]["cpp"]
    assert cpp_pkg["degraded"] is False
    ue = result["import_graphs"]["cpp-unreal"]
    assert ue["degraded"] is False

    verdicts = [e for e in result["errors"] if isinstance(e, dict)]
    by_builder = {v["builder"]: v for v in verdicts}
    assert by_builder["dep_graph:import-graph.py"]["degraded"] is True
    assert by_builder["dep_graph:madge"]["degraded"] is True
    assert by_builder["dep_graph:cargo metadata"]["metric"] == "not-applicable"
    assert by_builder["dep_graph:cmake --graphviz"]["metric"] == "not-applicable"
    assert by_builder["dep_graph:grep *.Build.cs"]["metric"] == "not-applicable"


def test_producer_with_missing_structural_denominator_defaults_to_degraded_not_healthy(
        tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()  # NO structural.json at all
    _resolve_stub(monkeypatch)
    _no_op_packages(monkeypatch)
    monkeypatch.setattr(dep_graph, "_import_graphs_from_scanner",
                         lambda root: ({"python": _graph("import-graph.py", ["a.py"] * 50)}, []))
    monkeypatch.setattr(dep_graph, "_madge_typescript", lambda root, universe: None)

    result = dep_graph.build(root)
    py = result["import_graphs"]["python"]
    assert py["degraded"] is True
    assert "denominator" in py["reason"] or "unavailable" in py["reason"]


def test_cpp_and_ue_package_graphs_report_metric_not_applicable_without_fabricated_ratio(
        tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    _structural(root, {"cpp": {"files": 2}}, total_files=2)
    _resolve_stub(monkeypatch, discovery_mode="build-cs", collect_packages=True)
    monkeypatch.setattr(dep_graph, "_import_graphs_from_scanner", lambda root: ({}, []))
    monkeypatch.setattr(dep_graph, "_madge_typescript", lambda root, universe: None)
    monkeypatch.setattr(dep_graph, "_python_package_graph", lambda root: (None, []))
    monkeypatch.setattr(dep_graph, "_rust_package_graph", lambda root: (None, []))
    # Node count deliberately exceeds any possible file-based universe — if the
    # metric were fabricated as a ratio it would read > 1.0, which is exactly
    # the "plausible-costume" number D-002 forbids.
    monkeypatch.setattr(dep_graph, "_cpp_package_graph",
                         lambda root: (_graph("cmake --graphviz", ["n1", "n2", "n3", "n4"]), []))
    monkeypatch.setattr(dep_graph, "_ue_import_graph",
                         lambda root, excl, universe: _graph(
                             "grep *.Build.cs", ["Mod1", "Mod2", "Mod3", "Mod4", "Mod5"]))

    result = dep_graph.build(root)
    cpp_pkg = result["package_graphs"]["cpp"]
    assert cpp_pkg["degraded"] is False
    ue = result["import_graphs"]["cpp-unreal"]
    assert ue["degraded"] is False

    verdicts = {e["builder"]: e for e in result["errors"] if isinstance(e, dict)}
    for builder in ("dep_graph:cmake --graphviz", "dep_graph:grep *.Build.cs"):
        v = verdicts[builder]
        assert v["metric"] == "not-applicable"
        assert v["universe"] is None
        assert v["ratio"] is None
        assert v["degraded"] is False


# --------------------------------------------------------------------- AC-5

def test_richer_candidate_graph_kept_over_poorer_same_language(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    _structural(root, {"typescript": {"files": 20}}, total_files=20)
    _resolve_stub(monkeypatch)
    _no_op_packages(monkeypatch)
    monkeypatch.setattr(
        dep_graph, "_import_graphs_from_scanner",
        lambda root: ({"typescript": _graph(
            "import-graph.py", [f"f{i}.ts" for i in range(10)],
            [("f0.ts", "f1.ts")])}, []))
    monkeypatch.setattr(
        dep_graph, "_madge_typescript",
        lambda root, universe: {**_graph("madge", ["f0.ts"]), "errors": []})

    result = dep_graph.build(root)
    ts = result["import_graphs"]["typescript"]
    assert ts["tool"] == "import-graph.py"
    assert len(ts["nodes"]) == 10
    assert ts["degraded"] is False

    discarded = [e for e in result["errors"]
                 if isinstance(e, dict) and e["builder"] == "dep_graph:madge"]
    assert discarded and discarded[0]["observed"] == 1


def test_poorer_madge_result_does_not_overwrite_richer_scanner_graph(tmp_path, monkeypatch):
    """The ticket's originating bug, pinned as an executable regression: a
    ~207-file scanner graph must never be silently replaced by madge's
    1-node/0-edge result."""
    root = tmp_path / "proj"
    root.mkdir()
    _structural(root, {"typescript": {"files": 207}}, total_files=207)
    _resolve_stub(monkeypatch)
    _no_op_packages(monkeypatch)
    rich_files = [f"src/f{i}.ts" for i in range(200)]
    monkeypatch.setattr(
        dep_graph, "_import_graphs_from_scanner",
        lambda root: ({"typescript": _graph(
            "import-graph.py", rich_files,
            [("src/f0.ts", "src/f1.ts")] * 5)}, []))
    monkeypatch.setattr(
        dep_graph, "_madge_typescript",
        lambda root, universe: {**_graph("madge", ["src/f0.ts"]), "errors": []})

    result = dep_graph.build(root)
    ts = result["import_graphs"]["typescript"]
    assert ts["tool"] == "import-graph.py"
    assert len(ts["nodes"]) == 200
    assert ts["degraded"] is False


# --------------------------------------------------------------------- AC-6

def test_madge_invoked_with_extensions_and_tsconfig_when_tsconfig_present(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "package.json").write_text("{}", encoding="utf-8")
    (root / "tsconfig.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dep_graph.shutil, "which", lambda name: "/usr/bin/madge")
    monkeypatch.setattr(dep_graph, "_resolve", lambda field: "")

    captured = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "{}"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompleted()

    monkeypatch.setattr(dep_graph.subprocess, "run", fake_run)
    dep_graph._madge_typescript(root, [])
    cmd = captured["cmd"]
    assert "--extensions" in cmd
    assert cmd[cmd.index("--extensions") + 1] == "ts,tsx,js,jsx"
    assert "--ts-config" in cmd
    assert cmd[cmd.index("--ts-config") + 1] == str(root / "tsconfig.json")


def test_madge_invoked_without_ts_config_flag_when_no_tsconfig_present(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dep_graph.shutil, "which", lambda name: "/usr/bin/madge")
    monkeypatch.setattr(dep_graph, "_resolve", lambda field: "")

    captured = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "{}"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompleted()

    monkeypatch.setattr(dep_graph.subprocess, "run", fake_run)
    dep_graph._madge_typescript(root, [])
    cmd = captured["cmd"]
    assert "--extensions" in cmd
    assert "--ts-config" not in cmd
