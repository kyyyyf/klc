"""KLC-105 step-6 — the walk-fallback degrade path (AC-9) and the empty-universe
degrade case (AC-9, C-005).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[2]
_skills = _repo_root / "core" / "skills"
sys.path.insert(0, str(_skills))
import file_scanner  # noqa: E402
import file_universe  # noqa: E402
import callgraph_python  # noqa: E402

# KLC-136 AC-3 (F-012 group (b)): redirect PROJECT_ROOT to an empty per-test
# project — file_universe.resolve(root) with no `structural=` passed falls
# back to klc_index_dir()/structural.json, which is PROJECT_ROOT-governed,
# NOT root-governed; a live or stand-in index must never be consulted.
pytestmark = pytest.mark.usefixtures("hermetic_project_root")


def _no_git_path_env() -> dict:
    """A PATH with every 'git' binary removed, so subprocess git calls fail with
    FileNotFoundError-equivalent (git unavailable), matching the "no .git" degrade
    case without needing to hide a real .git directory from a nested test runner."""
    env = dict(os.environ)
    parts = env.get("PATH", "").split(os.pathsep)
    kept = []
    for d in parts:
        if not d:
            continue
        if (Path(d) / "git").exists() or (Path(d) / "git.exe").exists():
            continue
        kept.append(d)
    env["PATH"] = os.pathsep.join(kept)
    return env


def test_walk_fallback_marker_when_git_unavailable(tmp_path, monkeypatch):
    """AC-9: a fixture directory with NO .git, containing files plus a would-be-
    polluting subtree; the full builder chain resolves to files_rel_source=="walk",
    and two independently-invoked builders (file_scanner and callgraph_python)
    resolve to the SAME file set — one shared walked list, not two independent
    walks reaching the same answer by coincidence."""
    root = tmp_path / "no_git_proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text(
        "def public_fn():\n    return 1\n", encoding="utf-8")
    # A would-be-polluting subtree — with no git at all, EVERYTHING is walked
    # (this is the documented, non-reproducible degrade path, not a closure claim).
    (root / "extra").mkdir()
    (root / "extra" / "more.py").write_text(
        "def more_fn():\n    return 2\n", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda name: None if name == "git" else shutil.which(name))
    env = _no_git_path_env()
    monkeypatch.setattr(os, "environ", env)

    structural = file_scanner.scan(root)
    assert structural["files_rel_source"] == "walk"

    py_files = callgraph_python.collect_python_files(root, None)
    py_rel = sorted(str(f.relative_to(root)).replace("\\", "/") for f in py_files)
    assert py_rel == sorted(
        f for f in structural["files_rel"] if f.endswith(".py"))


def test_empty_universe_degrades_not_crashes(tmp_path):
    """AC-9/C-005: an empty repo (git present, zero tracked files) still produces
    artifacts with a recorded note and process exit 0, never a crash."""
    root = tmp_path / "empty_repo"
    root.mkdir()
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(root), check=True)
    # An empty COMMIT (not zero commits): HEAD must resolve (init --finalize needs
    # it) while git ls-files still returns [] — zero TRACKED files.
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "empty"],
                   cwd=str(root), check=True)

    resolved = file_universe.resolve(root)
    assert resolved["files"] == []
    assert any("empty" in n for n in resolved["notes"])

    init_script = _repo_root / "scripts" / "init.py"
    r = subprocess.run(
        [sys.executable, str(init_script), "--scan-only"],
        cwd=str(root), capture_output=True, text=True, timeout=60,
        env={**os.environ, "PROJECT_ROOT": str(root)},
    )
    assert r.returncode == 0, f"init --scan-only crashed on an empty repo:\n{r.stdout}\n{r.stderr}"
    assert (root / ".klc" / "index" / "structural.json").exists()


@pytest.mark.parametrize("live_index_state", ["stale"], indirect=True)
def test_verdict_unchanged_with_project_root_redirected(live_index_state, no_index_reads, tmp_path):
    """AC-3: file_universe.resolve(root)'s empty-universe degrade verdict is
    unaffected by PROJECT_ROOT, and the check never reads a live or
    stand-in .klc/index/ (its implicit structural.json fallback is
    PROJECT_ROOT-governed, not root-governed)."""
    root = tmp_path / "empty_repo"
    root.mkdir()
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "empty"],
                   cwd=str(root), check=True)

    resolved = file_universe.resolve(root)
    assert resolved["files"] == []
    assert any("empty" in n for n in resolved["notes"])
    assert no_index_reads() == []
