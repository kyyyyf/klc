"""KLC-105 step-5 — planning_validate reports out-of-universe paths (AC-7).

Runs the real planning_validate.py CLI over a hand-built polluted artifact set (one
out-of-universe path injected into EACH of the six AC-2 categories: depgraph,
inventory, test_map, file_roles, symbol_usage, modules) and asserts one warning per
category, exit code 0 by default, and --strict escalates to non-zero.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[2]
_skills = _repo_root / "core" / "skills"

_POLLUTED = ".claude/worktrees/agent-x/pkg/bad.py"
_GOOD = "pkg/mod.py"


def _write_polluted_artifacts(tmp_path: Path) -> dict[str, Path]:
    structural = {"root": str(tmp_path), "files_rel": [_GOOD]}
    depgraph = {"import_graphs": {"python": {
        "nodes": [{"id": _GOOD}, {"id": _POLLUTED}], "edges": []}}}
    inventory = {"symbols": [{"file": _GOOD}, {"file": _POLLUTED}]}
    test_map = {"production_to_tests": {
        _GOOD: {"coverage": "none", "tests": []},
        _POLLUTED: {"coverage": "none", "tests": []}}}
    file_roles = {"files": {_GOOD: {}, _POLLUTED: {}}}
    symbol_usage = {"symbols": {
        f"{_GOOD}::fn": {"defined_in": _GOOD, "used_by": [{"file": _POLLUTED}],
                         "tested_by": []}}}
    modules = {"modules": [
        {"name": "pkg", "path": "pkg/", "files": [_GOOD, _POLLUTED]}], "files": {}}
    module_edges = {"edges": []}

    paths = {}
    for name, data in (
        ("structural", structural), ("depgraph", depgraph),
        ("inventory", inventory), ("test_map", test_map),
        ("file_roles", file_roles), ("symbol_usage", symbol_usage),
        ("modules", modules), ("module_edges", module_edges),
    ):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        paths[name] = p
    return paths


def _run_validate(paths: dict[str, Path], extra_args: list[str] | None = None):
    script = _skills / "planning_validate.py"
    cmd = [
        sys.executable, str(script),
        "--in-modules", str(paths["modules"]),
        "--in-file-roles", str(paths["file_roles"]),
        "--in-module-edges", str(paths["module_edges"]),
        "--in-structural", str(paths["structural"]),
        "--in-depgraph", str(paths["depgraph"]),
        "--in-test-map", str(paths["test_map"]),
        "--in-symbol-usage", str(paths["symbol_usage"]),
        "--in-inventory", str(paths["inventory"]),
    ]
    cmd.extend(extra_args or [])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def test_out_of_universe_paths_reported_as_warnings(tmp_path):
    """AC-7: one warning entry per out-of-universe path, across all six AC-2
    categories (depgraph, inventory, test_map, file_roles, symbol_usage, modules —
    symbol_usage per D-102), with exit code 0 (advisory, not fail-closed)."""
    paths = _write_polluted_artifacts(tmp_path)
    r = _run_validate(paths)
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)

    universe_warnings = [w for w in report["warnings"] if _POLLUTED in w]
    categories_flagged = {w.split(" references", 1)[0] for w in universe_warnings}
    assert categories_flagged == {
        "depgraph", "inventory", "test_map", "file_roles", "symbol_usage", "modules",
    }, categories_flagged
    assert report["counts"]["universe_checked"] is True
    assert report["counts"]["out_of_universe"] == len(universe_warnings) == 6


def test_strict_flag_escalates_to_nonzero_exit(tmp_path):
    """AC-7 negative / fail-closed twin: --strict escalates the same warnings to a
    non-zero exit code, while the default (no --strict) run stays exit 0 (C-005)."""
    paths = _write_polluted_artifacts(tmp_path)

    default_run = _run_validate(paths)
    assert default_run.returncode == 0

    strict_run = _run_validate(paths, extra_args=["--strict"])
    assert strict_run.returncode != 0
    report = json.loads(strict_run.stdout)
    assert report["warnings"]
