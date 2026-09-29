"""KLC-105 — non-python backends respect the same universe (AC-8).

Each row builds a small fixture GIT repo with tracked sources in one language plus
an UNTRACKED polluting subtree (mirroring ``.claude/worktrees/agent-x/...``) that
contains a file in the SAME language, then runs the real builder CLI and asserts
every emitted node/file is a member of ``files_rel``.

test_typescript_import_graph_excludes_pollution is added at step-2 (import-graph.py).
test_rust_callgraph_excludes_pollution / test_cpp_callgraph_excludes_pollution /
test_astgrep_inventory_excludes_untracked_pollution are added at steps 3-4.
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
import file_scanner  # noqa: E402
import deterministic_inventory as di  # noqa: E402
import callgraph_rust_async as cg_rust  # noqa: E402
import callgraph_cpp as cg_cpp  # noqa: E402

# KLC-136 AC-3 (F-012 group (b)): redirect PROJECT_ROOT to an empty per-test
# project — the ast-grep inventory path's implicit universe resolution must
# never consult a live or stand-in .klc/index/.
pytestmark = pytest.mark.usefixtures("hermetic_project_root")


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _init_git_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")


def _commit_all(root: Path, msg: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


def test_typescript_import_graph_excludes_pollution(tmp_path):
    """AC-8: fixture repo with tracked .ts sources + untracked polluting subtree
    under a .claude/worktrees/... path containing a .ts file; run import-graph.py;
    assert 0 typescript nodes outside files_rel (baseline pre-fix: 50/55)."""
    root = tmp_path / "ts_fixture"
    _init_git_repo(root)

    src = root / "src"
    src.mkdir()
    (src / "index.ts").write_text(
        "import { helper } from './helper';\nexport const x = helper();\n",
        encoding="utf-8")
    (src / "helper.ts").write_text(
        "export function helper() { return 1; }\n", encoding="utf-8")
    _commit_all(root, "seed tracked ts sources")

    # Untracked polluting subtree — mirrors .claude/worktrees/agent-x/... but never
    # git-added, so it must never appear in files_rel or any derived artifact.
    pollution_dir = root / ".claude" / "worktrees" / "agent-x" / "src"
    pollution_dir.mkdir(parents=True)
    (pollution_dir / "polluted_marker_mod.ts").write_text(
        "export const KLC105_POLLUTION_MARKER = 1;\n", encoding="utf-8")

    structural = file_scanner.scan(root)
    assert not any(f.startswith(".claude/") for f in structural["files_rel"]), (
        "fixture setup bug: pollution leaked into files_rel before the assertion")

    struct_path = tmp_path / "structural.json"
    struct_path.write_text(json.dumps(structural), encoding="utf-8")
    script = _skills / "import-graph.py"
    r = subprocess.run(
        [sys.executable, str(script), "--structural", str(struct_path)],
        capture_output=True, text=True, cwd=str(root), timeout=60,
    )
    assert r.returncode == 0, f"import-graph.py failed: {r.stderr}"
    graphs = json.loads(r.stdout)
    ts = graphs.get("typescript", {})
    nodes = [n["id"] for n in ts.get("nodes", [])]
    edges = ts.get("edges", [])

    universe = set(structural["files_rel"])
    node_violations = [n for n in nodes if n not in universe]
    edge_violations = [e for e in edges
                       if e.get("from") not in universe or e.get("to") not in universe]
    assert node_violations == [], f"out-of-universe ts node(s): {node_violations}"
    assert edge_violations == [], f"out-of-universe ts edge(s): {edge_violations}"
    assert not any("polluted_marker_mod" in n for n in nodes)


def _astgrep_or_skip():
    import tools
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def test_astgrep_inventory_excludes_untracked_pollution(tmp_path):
    """AC-8: extends test_deterministic_inventory.py's
    test_astgrep_path_honours_profile_excludes, but for UNTRACKED pollution OUTSIDE
    any profile-exclude pattern AND outside _HIDDEN_OR_NOISE's dot-directory check
    (the real gap this ticket closes for deterministic_inventory specifically: a
    PLAIN untracked directory name — like an ad-hoc working copy — matches neither
    the UE profile's excludes-regex, ``_HIDDEN_OR_NOISE``, nor any dotfile
    convention, so the pre-fix ``ast-grep scan --config <cfg> .`` over the whole
    tree picked it up regardless). Skips (not fails) when ast-grep is absent,
    matching _astgrep_or_skip()."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    _init_git_repo(root)
    (root / "pkg" / "mod.py").write_text(
        "def public_fn(a, b):\n    return a + b\n", encoding="utf-8")
    _commit_all(root, "seed tracked production file")

    pollution_dir = root / "untracked_scratch_copy" / "pkg"
    pollution_dir.mkdir(parents=True)
    (pollution_dir / "polluted_mod.py").write_text(
        "def klc105_untracked_pollution_marker():\n    return 0\n", encoding="utf-8")

    ruleset = di.resolve_ruleset()
    astgrep = _astgrep_or_skip()
    inv = di.build_inventory(root, ruleset, astgrep)
    names = {s["name"] for s in inv["symbols"]}
    files = {s["file"] for s in inv["symbols"]}
    assert "public_fn" in names
    assert "klc105_untracked_pollution_marker" not in names, (
        "untracked pollution outside any profile-exclude pattern leaked into the "
        "ast-grep inventory")
    assert not any(f.startswith("untracked_scratch_copy/") for f in files)


def test_rust_callgraph_excludes_pollution(tmp_path):
    """AC-8: fixture repo with tracked .rs sources + polluting subtree containing a
    .rs file; every file collect_rust_files() would open is a member of files_rel.
    Asserts over the file-collection entry point (not a full rust-analyzer LSP run)
    — that seam is exactly what this ticket changes, and it keeps this test runnable
    without rust-analyzer installed."""
    root = tmp_path / "rust_fixture"
    _init_git_repo(root)
    src = root / "src"
    src.mkdir()
    (src / "lib.rs").write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n",
                                encoding="utf-8")
    _commit_all(root, "seed tracked rust sources")

    pollution_dir = root / ".claude" / "worktrees" / "agent-x" / "src"
    pollution_dir.mkdir(parents=True)
    (pollution_dir / "polluted.rs").write_text(
        "pub fn klc105_rust_pollution_marker() -> i32 { 0 }\n", encoding="utf-8")

    files = cg_rust.collect_rust_files(root)
    rel_files = [str(f.relative_to(root)).replace("\\", "/") for f in files]
    universe = set(file_scanner.scan(root)["files_rel"])
    violations = [f for f in rel_files if f not in universe]
    assert violations == [], f"out-of-universe rust file(s): {violations}"
    assert not any("polluted" in f for f in rel_files)


def test_cpp_callgraph_excludes_pollution(tmp_path):
    """AC-8: fixture repo with tracked .cpp/.hpp sources + polluting subtree
    containing a .cpp (referenced from compile_commands.json, an EXTERNAL artifact
    this module cannot constrain) and a .hpp; every file collect_header_files() /
    collect_tu_files() (post-filtered via _filter_to_universe) would open is a
    member of files_rel. Asserts over the file-collection entry points (not a full
    clangd LSP run) — runnable without clangd installed."""
    root = tmp_path / "cpp_fixture"
    _init_git_repo(root)
    src = root / "src"
    src.mkdir()
    (src / "main.cpp").write_text(
        "int add(int a, int b) { return a + b; }\n", encoding="utf-8")
    (src / "lib.hpp").write_text(
        "inline int square(int x) { return x * x; }\n", encoding="utf-8")
    _commit_all(root, "seed tracked cpp sources")

    pollution_dir = root / ".claude" / "worktrees" / "agent-x" / "src"
    pollution_dir.mkdir(parents=True)
    (pollution_dir / "polluted.cpp").write_text(
        "int klc105_cpp_pollution_marker() { return 0; }\n", encoding="utf-8")
    (pollution_dir / "polluted.hpp").write_text(
        "inline int klc105_cpp_header_marker() { return 0; }\n", encoding="utf-8")

    compdb = [
        {"directory": str(src), "file": "main.cpp",
         "command": "c++ -c main.cpp"},
        {"directory": str(pollution_dir), "file": "polluted.cpp",
         "command": "c++ -c polluted.cpp"},
    ]

    universe = set(file_scanner.scan(root)["files_rel"])

    headers = cg_cpp.collect_header_files(root)
    header_rel = [str(f.relative_to(root)).replace("\\", "/") for f in headers]
    assert [f for f in header_rel if f not in universe] == []
    assert not any("polluted" in f for f in header_rel)

    tus = cg_cpp.collect_tu_files(compdb)
    filtered_tus = cg_cpp._filter_to_universe(tus, root, universe)
    tu_rel = [str(f.relative_to(root)).replace("\\", "/") for f in filtered_tus]
    assert [f for f in tu_rel if f not in universe] == []
    assert not any("polluted" in f for f in tu_rel)
    assert "src/main.cpp" in tu_rel


@pytest.mark.parametrize("live_index_state", ["stale"], indirect=True)
def test_verdict_unchanged_with_project_root_redirected(live_index_state, no_index_reads, tmp_path):
    """AC-3: the ast-grep inventory's exclusion of untracked pollution is
    unaffected by PROJECT_ROOT, and the check never reads a live or
    stand-in .klc/index/."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    _init_git_repo(root)
    (root / "pkg" / "mod.py").write_text(
        "def public_fn(a, b):\n    return a + b\n", encoding="utf-8")
    _commit_all(root, "seed tracked production file")

    pollution_dir = root / "untracked_scratch_copy" / "pkg"
    pollution_dir.mkdir(parents=True)
    (pollution_dir / "polluted_mod.py").write_text(
        "def klc105_untracked_pollution_marker():\n    return 0\n", encoding="utf-8")

    ruleset = di.resolve_ruleset()
    astgrep = _astgrep_or_skip()
    inv = di.build_inventory(root, ruleset, astgrep)
    names = {s["name"] for s in inv["symbols"]}
    files = {s["file"] for s in inv["symbols"]}
    assert "public_fn" in names
    assert "klc105_untracked_pollution_marker" not in names
    assert not any(f.startswith("untracked_scratch_copy/") for f in files)
    assert no_index_reads() == []
