"""KLC-105 — real-repo closure tests (AC-3, AC-4, AC-6).

Runs against THIS checkout (PROJECT_ROOT=/home/ek/projects/klc), never a fixture,
per spec.md AC-6 ("rather than over a fixture") and test-plan.md ("not a fixture").
Precedent: tests/integration/test_klc057_real_repo.py.

Step-1 contributed ``test_structural_counters_equal_universe`` (AC-4). Step-2 adds
the python-import-graph rows (AC-3). Step-6 adds the six-category full-index gate
(AC-6, D-101 — no ``git clone``, see build-log.md).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[2]
_skills = _repo_root / "core" / "skills"
sys.path.insert(0, str(_skills))
import file_scanner  # noqa: E402
import file_universe  # noqa: E402
import deterministic_inventory as di  # noqa: E402
import modules_build  # noqa: E402
import test_map  # noqa: E402
import file_roles  # noqa: E402
import symbol_usage  # noqa: E402


def _load_hyphenated(name: str, path: Path):
    """Import a hyphenated-filename module (e.g. import-graph.py) by file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _git_available() -> bool:
    return shutil.which("git") is not None


def _worktrees_populated() -> bool:
    wt = _repo_root / ".claude" / "worktrees"
    return wt.is_dir() and any(wt.iterdir())


def test_structural_counters_equal_universe():
    """AC-4: total_files equals len(files_rel), and the sum of directory_tree[].files
    equals that same number — the structural scan counters count ONLY the resolved
    universe, not an independent working-tree walk.

    Baseline before the fix (measured 2026-09-16 on this checkout):
    total_files=4978 vs len(files_rel)=486.
    """
    result = file_scanner.scan(_repo_root)
    files_rel = result["files_rel"]
    assert result["total_files"] == len(files_rel), (
        f"total_files={result['total_files']} != len(files_rel)={len(files_rel)}")
    tree_sum = sum(e["files"] for e in result["directory_tree"])
    assert tree_sum == len(files_rel), (
        f"directory_tree sum={tree_sum} != len(files_rel)={len(files_rel)}")


def _run_import_graph_on_repo(structural: dict, tmp_path: Path) -> dict:
    """Run import-graph.py READ-ONLY against this checkout: it prints to stdout and
    writes no index artifact, so this never mutates .klc/index/ (Q-004 note)."""
    struct_path = tmp_path / "structural.json"
    struct_path.write_text(json.dumps(structural), encoding="utf-8")
    script = _skills / "import-graph.py"
    r = subprocess.run(
        [sys.executable, str(script), "--structural", str(struct_path)],
        capture_output=True, text=True, cwd=str(_repo_root), timeout=120,
    )
    assert r.returncode == 0, f"import-graph.py failed: {r.stderr}"
    return json.loads(r.stdout)


def test_python_import_graph_excludes_worktrees(tmp_path):
    """AC-3: the python import graph of THIS repository excludes every
    agent-worktree copy — built at current HEAD with .claude/worktrees populated,
    its node count under .claude/ is 0.

    Baseline pre-fix (measured 2026-09-16): 2640 such nodes out of 2951.
    """
    if not _git_available():
        pytest.skip("git unavailable (Q-004)")
    if not _worktrees_populated():
        pytest.skip(".claude/worktrees not populated on this checkout (Q-004)")

    structural = file_scanner.scan(_repo_root)
    graphs = _run_import_graph_on_repo(structural, tmp_path)
    py = graphs.get("python", {})
    nodes = [n["id"] for n in py.get("nodes", [])]
    polluted = [n for n in nodes if n.startswith(".claude/")]
    assert polluted == [], (
        f"{len(polluted)}/{len(nodes)} python import-graph node(s) under .claude/: "
        f"{polluted[:5]}")


def test_closure_check_fails_when_pollution_present(tmp_path, monkeypatch):
    """Negative twin (AC-3 / AC-6): monkeypatch file_scanner.resolved_file_universe
    to return the PRE-fix (unfiltered) walk for the duration of one call, confirming
    the closure predicate flags the .claude/worktrees nodes as violations — proves
    the integration suite would actually catch a regression, not a fixture-shaped
    stand-in that happens to always pass."""
    if not _git_available():
        pytest.skip("git unavailable (Q-004)")
    if not _worktrees_populated():
        pytest.skip(".claude/worktrees not populated on this checkout (Q-004)")

    # The correct universe (what files_rel SHOULD be).
    good_structural = file_scanner.scan(_repo_root)
    good_universe = good_structural["files_rel"]

    # Simulate the pre-fix bug: an unfiltered rglob walk with NO excludes at all,
    # so .claude/worktrees is fully present — the exact defect this ticket removes.
    def _unfiltered_walk(root, excludes_re):
        walked = []
        for p in Path(root).rglob("*"):
            if p.is_file():
                try:
                    walked.append(str(p.relative_to(root)).replace("\\", "/"))
                except ValueError:
                    continue
        return sorted(walked), "walk"

    monkeypatch.setattr(file_scanner, "resolved_file_universe", _unfiltered_walk)
    polluted_structural = file_scanner.scan(_repo_root)
    monkeypatch.undo()  # restore for the rest of this call and any later ones

    graphs = _run_import_graph_on_repo(polluted_structural, tmp_path)
    py = graphs.get("python", {})
    nodes = [n["id"] for n in py.get("nodes", [])]

    violations = file_universe.out_of_universe(nodes, good_universe)
    polluted_violations = [v for v in violations if v.startswith(".claude/")]
    assert polluted_violations, (
        "closure predicate failed to flag any .claude/worktrees violation when fed "
        "a deliberately polluted (pre-fix-equivalent) structural.json — the "
        "regression-catching test itself is broken")


def test_full_index_closure_real_repo(tmp_path):
    """AC-6: builds the full index chain over THIS repository checkout under test
    (not a fixture) and applies the AC-2 closure predicate to every produced
    artifact category. D-101 (impl-plan-review F-1): does NOT `git clone` HEAD —
    a clone only replays tracked commit content, so it would contain NONE of the
    `.claude/worktrees/agent-*` pollution this epic targets (real `git worktree`
    linked checkouts, invisible to `git ls-files`/`git status`), making the gate
    pass identically before and after the fix. Instead every builder runs
    READ-ONLY against this checkout (PROJECT_ROOT=/home/ek/projects/klc): the
    build_* functions are pure (no I/O) and import-graph.py only prints — so
    `.klc/index/` is never written to. Skips with an explicit reason when
    `.claude/worktrees` is absent (a clean clone has nothing to catch, Q-004)."""
    if not _git_available():
        pytest.skip("git unavailable (Q-004)")
    if not _worktrees_populated():
        pytest.skip(".claude/worktrees not populated on this checkout (Q-004)")

    structural = file_scanner.scan(_repo_root)
    universe = structural["files_rel"]

    graphs = _run_import_graph_on_repo(structural, tmp_path)
    depgraph = {"import_graphs": graphs}

    ruleset = di.resolve_ruleset()
    import tools as _tools
    astgrep = _tools.resolve_tool("ast-grep")
    inventory = di.build_inventory(
        _repo_root, ruleset, str(astgrep) if astgrep else None, files=universe)

    modules = modules_build.build_modules(structural, depgraph, all_files=universe)
    tmap = test_map.build_test_map(structural, depgraph, modules, callgraph=None)
    froles = file_roles.build_file_roles(inventory, modules, structural)
    susage = symbol_usage.build_symbol_usage(inventory, modules, None, depgraph, structural)

    categories = file_universe.collect_index_paths(
        depgraph=depgraph, inventory=inventory, test_map=tmap,
        file_roles=froles, symbol_usage=susage, modules=modules)
    report = file_universe.closure_report(categories, universe)

    assert set(report) == {
        "depgraph", "inventory", "test_map", "file_roles", "symbol_usage", "modules",
    }, report
    for category, violations in sorted(report.items()):
        assert violations == [], f"{category} escaped the universe: {violations[:5]}"
