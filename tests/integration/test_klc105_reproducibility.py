"""KLC-105 step-6 — two checkouts of the same commit produce byte-identical index
artifacts (AC-5), and a real content difference IS detected (discriminating-power
twin, so the byte-identical assertion isn't vacuously true).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[2]
_init_script = _repo_root / "scripts" / "init.py"

_GENERATED_AT_RE = re.compile(r'"generated_at":\s*"[^"]*"')
_ROOT_RE = re.compile(r'"root":\s*"[^"]*"')

_ARTIFACTS = (
    "structural.json", "depgraph.json", "inventory.json", "test_map.json",
    "file_roles.json", "module_edges.json", "symbol_usage.json", "modules.json",
)


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")


def _seed_repo(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "pkg" / "mod.py").write_text(
        "def public_fn(a, b):\n    return a + b\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")


def _run_scan_only(root: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(_init_script), "--scan-only"],
        cwd=str(root), capture_output=True, text=True, timeout=120,
        env={**os.environ, "PROJECT_ROOT": str(root)},
    )
    assert r.returncode == 0, f"klc init --scan-only failed:\n{r.stdout}\n{r.stderr}"


def _normalised(idx: Path, name: str) -> str:
    p = idx / name
    if not p.exists():
        return "<absent>"
    text = p.read_text(encoding="utf-8")
    text = _GENERATED_AT_RE.sub('"generated_at": "<norm>"', text)
    text = _ROOT_RE.sub('"root": "<norm>"', text)
    data = json.loads(text)
    return json.dumps(data, sort_keys=True)


def test_byte_identical_across_checkouts_with_untracked_diff(tmp_path):
    """AC-5: two tmp checkouts of the SAME commit; checkout B additionally carries
    untracked pollution (.claude/worktrees/agent-y/..., a stray node_modules/); run
    klc init --scan-only in both; normalise root/generated_at; assert byte-identical
    JSON per artifact pair."""
    root_a = tmp_path / "checkout_a"
    root_b = tmp_path / "checkout_b"
    _seed_repo(root_a)
    _git(root_a, "clone", str(root_a), str(root_b))
    _git(root_b, "config", "user.email", "test@example.com")
    _git(root_b, "config", "user.name", "Test")
    _git(root_b, "config", "commit.gpgsign", "false")

    pollution = root_b / ".claude" / "worktrees" / "agent-y" / "pkg"
    pollution.mkdir(parents=True)
    (pollution / "bad.py").write_text(
        "def pollution_marker():\n    return 0\n", encoding="utf-8")
    nm = root_b / "node_modules" / "some-pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("module.exports = {};\n", encoding="utf-8")

    _run_scan_only(root_a)
    _run_scan_only(root_b)

    idx_a = root_a / ".klc" / "index"
    idx_b = root_b / ".klc" / "index"
    for name in _ARTIFACTS:
        a = _normalised(idx_a, name)
        b = _normalised(idx_b, name)
        assert a == b, f"{name} differs between checkouts:\nA={a}\nB={b}"


def test_different_commits_are_not_identical(tmp_path):
    """Negative twin (sanity power check): checkout B has one extra TRACKED file (a
    real content diff, i.e. a different commit) — the artifacts DIFFER, proving the
    comparator above has discriminating power."""
    root_a = tmp_path / "checkout_a2"
    root_b = tmp_path / "checkout_b2"
    _seed_repo(root_a)
    _git(root_a, "clone", str(root_a), str(root_b))
    _git(root_b, "config", "user.email", "test@example.com")
    _git(root_b, "config", "user.name", "Test")
    _git(root_b, "config", "commit.gpgsign", "false")

    (root_b / "pkg" / "extra.py").write_text(
        "def extra_fn():\n    return 1\n", encoding="utf-8")
    _git(root_b, "add", "-A")
    _git(root_b, "commit", "-q", "-m", "extra tracked file")

    _run_scan_only(root_a)
    _run_scan_only(root_b)

    idx_a = root_a / ".klc" / "index"
    idx_b = root_b / ".klc" / "index"
    differs = any(
        _normalised(idx_a, name) != _normalised(idx_b, name) for name in _ARTIFACTS)
    assert differs, "artifacts identical despite a real tracked-file content diff"
