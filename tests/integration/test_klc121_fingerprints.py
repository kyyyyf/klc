#!/usr/bin/env python3
"""KLC-121 step-3 — AC-1: `structural.json` publishes a per-file fingerprint
map. `test_klc107_incremental.py::test_structural_json_carries_stable_per_file_fingerprint`
carries the positive, real-repo case (KLC-107 AC-20); this file carries the
negative twin (a short map must be named) and the one-file-edit case."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import index_fingerprint  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args],
                    capture_output=True, text=True, timeout=15)


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def test_fingerprint_map_missing_a_files_rel_member_fails_schema_check():
    """AC-1 negative twin: a fixture `structural.json` whose fingerprint
    map omits one path present in `files_rel` must be named as missing by
    `check_map()`, not silently accepted as a short-but-valid map."""
    structural = {
        "files_rel": ["a.py", "b.py", "c.py"],
        "files": {
            "a.py": {"sha256": "x" * 64, "size": 1},
            "b.py": {"sha256": "y" * 64, "size": 2},
            # "c.py" is deliberately missing.
        },
    }
    errors = index_fingerprint.check_map(structural)
    assert any("c.py" in e for e in errors), errors
    assert any("missing" in e for e in errors), errors


def test_one_file_edit_changes_only_that_paths_fingerprint_entry(tmp_path):
    """AC-1/e2e: `klc init --scan-only` then one tracked file edited then
    `klc update` — the fingerprint map differs in exactly that path's
    entry, every other path's entry is byte-identical, and every OTHER
    artifact is still fully rewritten (this ticket ships no merge)."""
    repo = _make_repo(tmp_path)
    env = {"PROJECT_ROOT": str(repo)}
    import os
    full_env = dict(os.environ, **env)

    r = subprocess.run(
        [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "init.py"), "--scan-only"],
        cwd=str(repo), env=full_env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr

    structural_path = repo / ".klc" / "index" / "structural.json"
    inventory_path = repo / ".klc" / "index" / "inventory.json"
    before = json.loads(structural_path.read_text(encoding="utf-8"))
    inv_mtime_before = inventory_path.stat().st_mtime_ns

    (repo / "pkg" / "a.py").write_text("VALUE = 999\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "edit a.py")

    r = subprocess.run(
        [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "update.py")],
        cwd=str(repo), env=full_env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr

    after = json.loads(structural_path.read_text(encoding="utf-8"))
    inv_mtime_after = inventory_path.stat().st_mtime_ns

    assert before["files"]["pkg/a.py"] != after["files"]["pkg/a.py"]
    for path in before["files"]:
        if path == "pkg/a.py":
            continue
        assert before["files"][path] == after["files"][path], path

    # Non-goal boundary: no merge exists, so inventory.json (an "OTHER
    # artifact") must still be fully rewritten on every run.
    assert inv_mtime_after != inv_mtime_before


if __name__ == "__main__":
    import unittest
    unittest.main()
