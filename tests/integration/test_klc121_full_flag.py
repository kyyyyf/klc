#!/usr/bin/env python3
"""KLC-121 step-5 — AC-7: `klc update --full`.

Operator amendment 2026-09-20 (spec.md AC-7, design `[!DECISION D-201]`,
supersedes `D-007`): `--full` implies that the run happens — it suppresses
the `HEAD == .last-run` no-op on its own, `--force` keeps its existing
KLC-107 meaning unchanged, and the two flags are independent and
combinable.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = FRAMEWORK_ROOT / "scripts"


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
    r = subprocess.run([sys.executable, str(SCRIPTS / "init.py"), "--scan-only"],
                       cwd=str(root), env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    return root


def _update(root: Path, *flags: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PROJECT_ROOT=str(root))
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "update.py"), *flags],
        cwd=str(root), env=env, capture_output=True, text=True, timeout=120)


def test_update_full_alone_on_an_unchanged_head_rebuilds_instead_of_printing_update_noop(tmp_path):
    """The operator amendment to AC-7 (D-201, supersedes D-007; review
    finding F-1): on a tree where HEAD equals the recorded `.last-run` and
    with no `--force`, `klc update --full` must NOT print `UPDATE_NOOP`,
    must rebuild, and must log `full rebuild (reason: --full flag)`. The
    pre-existing `test_full_and_force_flags_are_independent_and_combinable`
    row only exercises the two flags together, so it cannot catch a
    `--full` that silently no-ops on its own — this is the row that bites."""
    repo = _make_repo(tmp_path)
    r = _update(repo, "--full")
    assert r.returncode == 0, r.stderr
    assert "UPDATE_NOOP" not in r.stdout
    assert "full rebuild (reason: --full flag)" in r.stdout
    assert "UPDATE_OK" in r.stdout


def test_update_full_forces_rebuild_and_logs_the_flag_as_reason(tmp_path):
    """AC-7: `klc update --full` on a tree with unchanged fingerprints (which
    would otherwise trigger no fallback condition) rebuilds every artifact
    and logs the AC-6 line as `full rebuild (reason: --full flag)`, not the
    no-trigger honest line."""
    repo = _make_repo(tmp_path)
    (repo / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "advance")

    r = _update(repo, "--full")
    assert r.returncode == 0, r.stderr
    assert "full rebuild (reason: --full flag)" in r.stdout
    assert "incremental merge not yet implemented" not in r.stdout


def test_force_flag_keeps_its_klc107_meaning(tmp_path):
    """AC-7: Q-003's working assumption: `klc update --force` continues to mean
    "run even though HEAD == .last-run" and does NOT by itself force a
    full-rebuild log reason — `--force` alone (fingerprints unchanged, HEAD
    unchanged) still triggers UPDATE_NOOP-avoidance without the `--full`
    log line."""
    repo = _make_repo(tmp_path)
    r = _update(repo, "--force")
    assert r.returncode == 0, r.stderr
    assert "UPDATE_NOOP" not in r.stdout
    assert "full rebuild (reason: --full flag)" not in r.stdout
    assert "incremental merge not yet implemented" in r.stdout


def test_full_and_force_flags_are_independent_and_combinable(tmp_path):
    """AC-7: `--full --force` together on a tree where HEAD == .last-run: neither
    UPDATE_NOOP (force's effect) nor a missing reason line (full's effect)
    — the two flags compose rather than one silently subsuming the other."""
    repo = _make_repo(tmp_path)
    r = _update(repo, "--full", "--force")
    assert r.returncode == 0, r.stderr
    assert "UPDATE_NOOP" not in r.stdout
    assert "full rebuild (reason: --full flag)" in r.stdout


if __name__ == "__main__":
    import unittest
    unittest.main()
