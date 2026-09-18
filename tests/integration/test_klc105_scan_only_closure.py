"""KLC-105 step-6 — the AC-2 six-category closure gate over a real `klc init
--scan-only` run (AC-2).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[2]
_skills = _repo_root / "core" / "skills"
_init_script = _repo_root / "scripts" / "init.py"
sys.path.insert(0, str(_skills))
import file_universe  # noqa: E402

_POLLUTED_MARKER = ".claude/worktrees/agent-x/pkg/bad.py"


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")


def _polluted_repo(tmp_path: Path) -> Path:
    root = tmp_path / "polluted_repo"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text(
        "def public_fn(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests" / "test_mod.py").write_text(
        "from pkg.mod import public_fn\n\n\ndef test_public_fn():\n"
        "    assert public_fn(1, 2) == 3\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed tracked project")

    pollution_dir = root / ".claude" / "worktrees" / "agent-x" / "pkg"
    pollution_dir.mkdir(parents=True)
    (pollution_dir / "bad.py").write_text(
        "def klc105_scan_only_pollution_marker():\n    return 0\n", encoding="utf-8")
    return root


def _run_scan_only(root: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(_init_script), "--scan-only"],
        cwd=str(root), capture_output=True, text=True, timeout=120,
        env={**os.environ, "PROJECT_ROOT": str(root)},
    )
    assert r.returncode == 0, f"klc init --scan-only failed:\n{r.stdout}\n{r.stderr}"


def _load(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _categories_and_universe(idx: Path) -> tuple[dict[str, list[str]], list[str]]:
    structural = _load(idx / "structural.json")
    categories = file_universe.collect_index_paths(
        depgraph=_load(idx / "depgraph.json"),
        inventory=_load(idx / "inventory.json"),
        test_map=_load(idx / "test_map.json"),
        file_roles=_load(idx / "file_roles.json"),
        symbol_usage=_load(idx / "symbol_usage.json"),
        modules=_load(idx / "modules.json"))
    return categories, structural.get("files_rel") or []


def test_scan_only_zero_paths_outside_universe(tmp_path):
    """AC-2: a real klc init --scan-only over a fixture with a polluting untracked
    subtree; per-category out-of-universe count is 0 for all six categories
    individually."""
    root = _polluted_repo(tmp_path)
    _run_scan_only(root)
    idx = root / ".klc" / "index"

    categories, universe = _categories_and_universe(idx)
    assert universe, "fixture produced an empty universe — test setup bug"
    report = file_universe.closure_report(categories, universe)

    assert set(report) == {
        "depgraph", "inventory", "test_map", "file_roles", "symbol_usage", "modules",
    }, report
    for category, violations in sorted(report.items()):
        assert violations == [], f"{category} escaped the universe: {violations}"


def test_closure_predicate_flags_injected_violation(tmp_path):
    """AC-2 negative twin: take the artifacts from the row above, inject one path
    under .claude/worktrees/agent-x/... into depgraph nodes and into a modules.json
    member-files list, run the shared closure-check helper against the doctored
    copy, assert it reports exactly the injected paths — proves the "zero"
    assertion above is not vacuously true."""
    root = _polluted_repo(tmp_path)
    _run_scan_only(root)
    idx = root / ".klc" / "index"

    depgraph = _load(idx / "depgraph.json")
    modules = _load(idx / "modules.json")
    structural = _load(idx / "structural.json")
    universe = structural.get("files_rel") or []

    # Inject the violation.
    depgraph.setdefault("import_graphs", {}).setdefault(
        "python", {"nodes": [], "edges": []})
    depgraph["import_graphs"]["python"].setdefault("nodes", []).append(
        {"id": _POLLUTED_MARKER})
    if modules.get("modules"):
        modules["modules"][0].setdefault("files", []).append(_POLLUTED_MARKER)
    else:
        modules["modules"] = [{"name": "injected", "path": "injected/",
                               "files": [_POLLUTED_MARKER]}]

    categories = file_universe.collect_index_paths(depgraph=depgraph, modules=modules)
    report = file_universe.closure_report(categories, universe)

    assert report["depgraph"] == [_POLLUTED_MARKER]
    assert report["modules"] == [_POLLUTED_MARKER]
