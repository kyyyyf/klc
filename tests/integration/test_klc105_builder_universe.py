"""KLC-105 — every builder consumes the SHARED universe, never a private walk (AC-1).

test_builder_does_not_walk_independently_of_missing_structural is added at step-3
(deterministic_inventory). test_all_builders_consume_shared_resolver (the full
ten-builder sweep) is added at step-4.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[2]
_skills = _repo_root / "core" / "skills"
sys.path.insert(0, str(_skills))
import deterministic_inventory as di  # noqa: E402
import file_scanner  # noqa: E402
import dep_graph  # noqa: E402
import modules_build  # noqa: E402
import test_map  # noqa: E402
import file_roles  # noqa: E402
import symbol_usage  # noqa: E402
import callgraph_python  # noqa: E402
import callgraph_cpp as cg_cpp  # noqa: E402
import callgraph_rust_async as cg_rust  # noqa: E402

# KLC-136 AC-3 (F-012 group (b)): redirect PROJECT_ROOT to an empty per-test
# project — build_inventory's implicit file_universe.resolve(root) fallback
# (files=None) must never consult a live or stand-in .klc/index/.
pytestmark = pytest.mark.usefixtures("hermetic_project_root")


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _polluted_fixture(tmp_path: Path) -> Path:
    """A fresh git repo (no structural.json anywhere for this root) with one
    tracked production file and an UNTRACKED polluting subtree carrying a unique
    marker symbol — mirrors .claude/worktrees/agent-x/... pollution."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "pkg" / "mod.py").write_text(
        "def public_fn(a, b):\n    return a + b\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed tracked production file")

    pollution_dir = root / ".claude" / "worktrees" / "agent-x" / "pkg"
    pollution_dir.mkdir(parents=True)
    (pollution_dir / "polluted_mod.py").write_text(
        "def klc105_pollution_marker_fn():\n    return 0\n", encoding="utf-8")
    return root


def _astgrep_or_skip():
    import tools
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def test_builder_does_not_walk_independently_of_missing_structural(tmp_path, monkeypatch):
    """AC-1 negative: invoke deterministic_inventory on the polluted fixture WITHOUT
    a pre-built structural.json anywhere for this root. The builder must still
    resolve its own universe via the shared resolver logic (file_universe →
    file_scanner's git-tracked resolver), not a private rglob / `scan --config . .`
    walk — the marker path/symbol must still be absent from the output, on BOTH the
    ast-grep path and the regex-fallback path."""
    root = _polluted_fixture(tmp_path)
    ruleset = di.resolve_ruleset()

    # ast-grep path (subprocess boundary — the positional PATHS list IS the proof
    # that no private walk happened; ast-grep only ever sees what it was handed).
    astgrep = _astgrep_or_skip()
    inv_ast = di.build_inventory(root, ruleset, astgrep)
    names_ast = {s["name"] for s in inv_ast["symbols"]}
    files_ast = {s["file"] for s in inv_ast["symbols"]}
    assert "klc105_pollution_marker_fn" not in names_ast
    assert not any(f.startswith(".claude/") for f in files_ast)

    # Regex-fallback path (in-process) — additionally prove NO rglob call happens
    # anywhere in the build by making Path.rglob raise if invoked.
    real_rglob = Path.rglob

    def _forbidden_rglob(self, *a, **kw):
        raise AssertionError(
            f"deterministic_inventory called Path.rglob({a!r}) on {self} — a "
            f"builder must resolve its universe via file_universe, never walk "
            f"independently (AC-1)")

    monkeypatch.setattr(Path, "rglob", _forbidden_rglob)
    try:
        inv_rx = di.build_inventory(root, ruleset, None)
    finally:
        monkeypatch.setattr(Path, "rglob", real_rglob)
    names_rx = {s["name"] for s in inv_rx["symbols"]}
    files_rx = {s["file"] for s in inv_rx["symbols"]}
    assert "klc105_pollution_marker_fn" not in names_rx
    assert not any(f.startswith(".claude/") for f in files_rx)


def _full_language_fixture(tmp_path: Path) -> Path:
    """A git repo with tracked py/ts/rust/cpp sources plus an UNTRACKED polluting
    subtree (mirrors .claude/worktrees/agent-x/...) carrying a unique marker symbol
    in EVERY language."""
    root = tmp_path / "full_proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")

    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text(
        "def public_fn(a, b):\n    return a + b\n", encoding="utf-8")
    src = root / "src"
    src.mkdir()
    (src / "index.ts").write_text(
        "export function tsFn() { return 1; }\n", encoding="utf-8")
    (src / "lib.rs").write_text(
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\n", encoding="utf-8")
    (src / "main.cpp").write_text(
        "int add(int a, int b) { return a + b; }\n", encoding="utf-8")
    (src / "lib.hpp").write_text(
        "inline int square(int x) { return x * x; }\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed tracked multi-language sources")

    pollution = root / ".claude" / "worktrees" / "agent-x"
    (pollution / "pkg").mkdir(parents=True)
    (pollution / "pkg" / "polluted_mod.py").write_text(
        "def klc105_pollution_marker_py():\n    return 0\n", encoding="utf-8")
    (pollution / "src").mkdir(parents=True)
    (pollution / "src" / "polluted.ts").write_text(
        "export function klc105PollutionMarkerTs() { return 0; }\n",
        encoding="utf-8")
    (pollution / "src" / "polluted.rs").write_text(
        "pub fn klc105_pollution_marker_rs() -> i32 { 0 }\n", encoding="utf-8")
    (pollution / "src" / "polluted.cpp").write_text(
        "int klc105_pollution_marker_cpp() { return 0; }\n", encoding="utf-8")
    (pollution / "src" / "polluted.hpp").write_text(
        "inline int klc105_pollution_marker_hpp() { return 0; }\n", encoding="utf-8")
    return root


_MARKER_TOKEN = "klc105_pollution_marker"
_MARKER_PATH_PREFIX = ".claude/"


def test_all_builders_consume_shared_resolver(tmp_path):
    """AC-1: invoke import-graph, deterministic_inventory, test_map, file_roles,
    symbol_usage, modules_build, callgraph_python, callgraph_cpp,
    callgraph_rust_async and file_scanner DIRECTLY (not only via klc init); assert
    the marker path/symbol is absent from every output."""
    root = _full_language_fixture(tmp_path)

    # 1. file_scanner — the structural counters + files_rel.
    structural = file_scanner.scan(root)
    assert not any(f.startswith(_MARKER_PATH_PREFIX) for f in structural["files_rel"])
    universe = set(structural["files_rel"])

    idx = root / ".klc" / "index"
    idx.mkdir(parents=True)
    (idx / "structural.json").write_text(json.dumps(structural), encoding="utf-8")

    # 2. import-graph.py (subprocess — prints, writes no artifact).
    ig_script = _skills / "import-graph.py"
    r = subprocess.run(
        [sys.executable, str(ig_script), "--structural", str(idx / "structural.json")],
        capture_output=True, text=True, cwd=str(root), timeout=60,
    )
    assert r.returncode == 0, r.stderr
    graphs = json.loads(r.stdout)
    for lang_graph in graphs.values():
        for node in lang_graph.get("nodes", []):
            assert not node["id"].startswith(_MARKER_PATH_PREFIX), node
        for edge in lang_graph.get("edges", []):
            assert not edge["from"].startswith(_MARKER_PATH_PREFIX)
            assert not edge["to"].startswith(_MARKER_PATH_PREFIX)

    # 3. dep_graph.build (wraps import-graph.py + UE/madge extras).
    depgraph = dep_graph.build(root)
    for lang_graph in depgraph.get("import_graphs", {}).values():
        for node in lang_graph.get("nodes", []):
            nid = node.get("id") if isinstance(node, dict) else node
            if nid:
                assert not nid.startswith(_MARKER_PATH_PREFIX)

    # 4. deterministic_inventory (regex fallback — no ast-grep dependency needed
    #    for this sweep; the ast-grep path is dedicated-tested elsewhere).
    ruleset = di.resolve_ruleset()
    inventory = di.build_inventory(root, ruleset, None, files=structural["files_rel"])
    inv_names = {s["name"] for s in inventory["symbols"]}
    inv_files = {s["file"] for s in inventory["symbols"]}
    assert not any(_MARKER_TOKEN in n.lower() for n in inv_names), inv_names
    assert not any(f.startswith(_MARKER_PATH_PREFIX) for f in inv_files)

    # 5. modules_build.
    modules = modules_build.build_modules(structural, depgraph, all_files=structural["files_rel"])
    for m in modules.get("modules", []):
        for f in m.get("files") or []:
            assert not f.startswith(_MARKER_PATH_PREFIX)
    for f in (modules.get("files") or {}):
        assert not f.startswith(_MARKER_PATH_PREFIX)

    # 6. test_map.
    tmap = test_map.build_test_map(structural, depgraph, modules, callgraph=None)
    for prod, entry in tmap["production_to_tests"].items():
        assert not prod.startswith(_MARKER_PATH_PREFIX)
        for t in entry["tests"]:
            assert not t["test_file"].startswith(_MARKER_PATH_PREFIX)
    for tests in tmap["module_to_tests"].values():
        for t in tests:
            assert not t.startswith(_MARKER_PATH_PREFIX)

    # 7. file_roles.
    froles = file_roles.build_file_roles(inventory, modules, structural)
    for path in froles["files"]:
        assert not path.startswith(_MARKER_PATH_PREFIX)

    # 8. symbol_usage.
    susage = symbol_usage.build_symbol_usage(inventory, modules, None, depgraph, structural)
    for key, meta in susage["symbols"].items():
        assert not key.startswith(_MARKER_PATH_PREFIX)
        assert not meta["defined_in"].startswith(_MARKER_PATH_PREFIX)
        for u in meta["used_by"]:
            assert not u["file"].startswith(_MARKER_PATH_PREFIX)
        for t in meta["tested_by"]:
            assert not t.startswith(_MARKER_PATH_PREFIX)

    # 9. callgraph_python (file-collection entry point).
    py_files = callgraph_python.collect_python_files(root, None)
    py_rel = [str(f.relative_to(root)).replace("\\", "/") for f in py_files]
    assert not any(f.startswith(_MARKER_PATH_PREFIX) for f in py_rel)

    # 10. callgraph_cpp / callgraph_rust_async (file-collection entry points).
    headers = cg_cpp.collect_header_files(root)
    header_rel = [str(f.relative_to(root)).replace("\\", "/") for f in headers]
    assert not any(f.startswith(_MARKER_PATH_PREFIX) for f in header_rel)

    compdb = [
        {"directory": str(root / "src"), "file": "main.cpp", "command": "c++ -c main.cpp"},
        {"directory": str(root / ".claude" / "worktrees" / "agent-x" / "src"),
         "file": "polluted.cpp", "command": "c++ -c polluted.cpp"},
    ]
    tus = cg_cpp._filter_to_universe(cg_cpp.collect_tu_files(compdb), root, universe)
    tu_rel = [str(f.relative_to(root)).replace("\\", "/") for f in tus]
    assert not any(f.startswith(_MARKER_PATH_PREFIX) for f in tu_rel)

    rust_files = cg_rust.collect_rust_files(root)
    rust_rel = [str(f.relative_to(root)).replace("\\", "/") for f in rust_files]
    assert not any(f.startswith(_MARKER_PATH_PREFIX) for f in rust_rel)


@pytest.mark.parametrize("live_index_state", ["stale"], indirect=True)
def test_verdict_unchanged_with_project_root_redirected(live_index_state, no_index_reads, tmp_path):
    """AC-3: the regex-fallback half of
    test_builder_does_not_walk_independently_of_missing_structural — the
    pollution marker stays absent, and the check never reads a live or
    stand-in .klc/index/."""
    root = _polluted_fixture(tmp_path)
    ruleset = di.resolve_ruleset()
    inv_rx = di.build_inventory(root, ruleset, None)
    names_rx = {s["name"] for s in inv_rx["symbols"]}
    files_rx = {s["file"] for s in inv_rx["symbols"]}
    assert "klc105_pollution_marker_fn" not in names_rx
    assert not any(f.startswith(".claude/") for f in files_rx)
    assert no_index_reads() == []
