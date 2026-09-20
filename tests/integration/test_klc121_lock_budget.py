#!/usr/bin/env python3
"""KLC-121 step-4 — AC-8: the fingerprint write and the fallback decision
both happen inside `index_lock.acquire_index_lock`'s existing critical
section, with the same `wait_s=0.0` direct-invocation contention policy as
before (C-003, F-009). Runs `scripts/update.py`'s `main()` IN-PROCESS (not
as a subprocess) so a spy on `index_fingerprint.decide()` can observe
whether the lock is held at the moment the fallback decision runs."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
SCRIPTS = FRAMEWORK_ROOT / "scripts"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(SCRIPTS))

import index_fingerprint  # noqa: E402
import index_lock as _index_lock  # noqa: E402
import update  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args],
                    capture_output=True, text=True, timeout=15)


def test_fingerprint_write_and_fallback_decision_happen_inside_the_existing_index_lock(
        tmp_path, monkeypatch):
    """AC-8: the fingerprint write and the fallback decision happen inside the existing
    index lock with the unchanged wait_s=0.0 direct-invocation policy (KLC-107 semantics)."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")

    monkeypatch.setenv("PROJECT_ROOT", str(root))
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "init.py"), "--scan-only"],
        cwd=str(root), env=dict(os.environ, PROJECT_ROOT=str(root)),
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr

    (root / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "advance")

    held = {"value": False}
    real_acquire = _index_lock.acquire_index_lock

    @contextlib.contextmanager
    def spy_acquire(index_dir, **kwargs):
        with real_acquire(index_dir, **kwargs) as lp:
            held["value"] = True
            try:
                yield lp
            finally:
                held["value"] = False

    observed_at_decide: list[bool] = []
    real_decide = index_fingerprint.decide

    def spy_decide(*args, **kwargs):
        observed_at_decide.append(held["value"])
        return real_decide(*args, **kwargs)

    monkeypatch.setattr(update._index_lock, "acquire_index_lock", spy_acquire)
    monkeypatch.setattr(index_fingerprint, "decide", spy_decide)

    cwd_before = os.getcwd()
    try:
        rc = update.main([])
    finally:
        os.chdir(cwd_before)

    assert rc == 0
    assert observed_at_decide, "index_fingerprint.decide() was never called"
    assert all(observed_at_decide), (
        "the fallback decision ran while the index lock was NOT held: "
        f"{observed_at_decide}")


if __name__ == "__main__":
    import unittest
    unittest.main()
