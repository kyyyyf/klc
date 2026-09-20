#!/usr/bin/env python3
"""KLC-121 step-4 — AC-6's seventh (no-trigger) branch, and C-004's negative
twin (no branch may read like a skip)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

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
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    env = dict(os.environ, PROJECT_ROOT=str(root))
    r = subprocess.run(
        [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "init.py"), "--scan-only"],
        cwd=str(root), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return root


def test_no_trigger_run_logs_the_honest_not_yet_implemented_line(tmp_path):
    """AC-6: Positive companion for the seventh (no-trigger) branch: an ordinary
    `klc update` run where none of the six fallback conditions changed
    prints the exact honest line, not a wording that could be read as a
    partial/incremental skip."""
    repo = _make_repo(tmp_path)
    (repo / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "advance")

    env = dict(os.environ, PROJECT_ROOT=str(repo))
    r = subprocess.run(
        [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "update.py")],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "full rebuild (incremental merge not yet implemented — KLC-125)" in r.stdout


@pytest.mark.parametrize("reason", (None, *index_fingerprint.REASONS),
                         ids=[r or "no-trigger" for r in (None, *index_fingerprint.REASONS)])
def test_fallback_log_never_claims_work_was_skipped(reason):
    """AC-6: NEGATIVE twin (C-004): across all seven branches (the six named
    reasons plus the no-trigger `None`), the formatted log line never
    contains wording that would imply partial work — every branch in this
    ticket IS a full rebuild."""
    forbidden = ("skip", "partial", "incremental applied", "applied incrementally")
    line = index_fingerprint.format_line(reason).lower()
    assert line.startswith("full rebuild"), line
    for word in forbidden:
        assert word not in line, (reason, line)


if __name__ == "__main__":
    import unittest
    unittest.main()
