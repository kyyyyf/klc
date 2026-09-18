#!/usr/bin/env python3
"""KLC-107 step-3 — index_lock: one writer at a time for `.klc/index/`
(finding F-1, [!DECISION D-201]).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS))
import index_lock as _lock  # noqa: E402

UPDATE = FRAMEWORK_ROOT / "scripts" / "update.py"
INIT = FRAMEWORK_ROOT / "scripts" / "init.py"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, timeout=15)


def _make_repo(tmp_path: Path) -> Path:
    """A real repo with enough files that the deterministic pipeline takes a
    non-trivial fraction of a second, widening the race window for the
    two-process contention test."""
    root = tmp_path / "proj"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    for i in range(20):
        (pkg / f"m{i}.py").write_text(f"def f{i}(x):\n    return x + {i}\n",
                                      encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")

    env = dict(os.environ, PROJECT_ROOT=str(root))
    r = subprocess.run([sys.executable, str(INIT), "--scan-only"],
                       cwd=str(root), env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr

    # Advance HEAD past the recorded baseline so update.py has real work to do.
    (pkg / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "extra")
    return root


def _run_update(root: Path) -> subprocess.Popen:
    env = dict(os.environ, PROJECT_ROOT=str(root))
    return subprocess.Popen([sys.executable, str(UPDATE)], cwd=str(root), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


_HOLDER_SRC = """
import json, sys, time
from pathlib import Path
sys.path.insert(0, {skills!r})
import index_lock as L
index_dir = Path(sys.argv[1])
ready_file = Path(sys.argv[2])
hold_s = float(sys.argv[3])
with L.acquire_index_lock(index_dir, wait_s=0.0):
    ready_file.write_text("1", encoding="utf-8")
    time.sleep(hold_s)
""".format(skills=str(SKILLS))


def _spawn_holder(index_dir: Path, ready_file: Path, hold_s: float) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", _HOLDER_SRC, str(index_dir), str(ready_file), str(hold_s)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _wait_for(path: Path, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{path} never appeared")
        time.sleep(0.02)


class TestTwoProcessContention(unittest.TestCase):
    """The genuine two-process RED (finding F-1): a second real writer must
    never interleave with the one currently holding the index lock.

    Racing two real `scripts/update.py` invocations against each other on a
    tiny fixture proved flaky in this sandbox: single/few-core scheduling
    routinely let the first process finish (acquire, run, release) before
    the second ever attempted `_try_create`, so both reported UPDATE_OK with
    no contention at all — a scheduling artifact, not a lock defect. A
    dedicated holder process that acquires the SAME `index_lock` and blocks
    for a bounded window, synchronised via a ready-file barrier, exercises
    the identical contended code path deterministically: one real process
    genuinely holds the lock, a second real process (`scripts/update.py`)
    is genuinely denied it. [!DECISION] tracked in build-log.md."""

    def test_two_concurrent_updates_one_wins_one_reports_busy(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="klc-test-klc107-lock-") as td:
            root = _make_repo(Path(td))
            index_dir = root / ".klc" / "index"
            ready = root / "_holder_ready"
            holder = _spawn_holder(index_dir, ready, hold_s=3.0)
            try:
                _wait_for(ready, timeout_s=10.0)
                # The holder is now GENUINELY holding the lock — update.py
                # (wait_s=0.0) must be denied immediately.
                p_busy = _run_update(root)
                out_busy, err_busy = p_busy.communicate(timeout=30)
                self.assertEqual(p_busy.returncode, 0, err_busy)
                self.assertIn("UPDATE_BUSY", out_busy)
                self.assertRegex(out_busy, r"PID \d+")
            finally:
                holder_out, holder_err = holder.communicate(timeout=30)
                self.assertEqual(holder.returncode, 0, holder_err)

            self.assertFalse(index_dir.joinpath(".lock").exists())

            # The holder released; a fresh update.py now gets the lock and
            # completes normally — proving the lock does not wedge shut.
            p_ok = _run_update(root)
            out_ok, err_ok = p_ok.communicate(timeout=120)
            self.assertEqual(p_ok.returncode, 0, err_ok)
            self.assertIn("UPDATE_OK", out_ok)

            last = index_dir.joinpath(".last-run").read_text(encoding="utf-8").strip()
            self.assertRegex(last, r"^[0-9a-f]{40}$")
            head = _git(root, "rev-parse", "HEAD").stdout.strip()
            self.assertEqual(last, head)
            self.assertFalse(index_dir.joinpath(".lock").exists())


class TestIndexLockSkill(unittest.TestCase):
    """Skill-level coverage of the reclaim / re-entrancy / release-on-raise
    behaviours — fast, no subprocess pipeline needed."""

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory(prefix="klc-test-klc107-lock-")
        self.index_dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_stale_lock_from_a_dead_pid_is_reclaimed(self):
        # A PID essentially guaranteed not to exist.
        dead_pid = 2_000_000_000
        lp = self.index_dir / ".lock"
        lp.write_text(json.dumps({"pid": dead_pid, "at": time.time()}), encoding="utf-8")
        with _lock.acquire_index_lock(self.index_dir, wait_s=0.0) as held:
            self.assertIsNotNone(held)
            rec = json.loads(lp.read_text(encoding="utf-8"))
            self.assertEqual(rec["pid"], os.getpid())
        self.assertFalse(lp.exists())

    def test_alive_holder_older_than_max_age_is_not_reclaimed(self):
        """review-fix (MEDIUM): MAX_LOCK_AGE_S must never reclaim a lock whose
        PID is VERIFIED alive — the real sequential worst case across
        update.py's builders can exceed 900s (finding), so an age-only
        ceiling on a still-running writer would reproduce the exact
        interleaved-write hazard D-201 exists to close. Age-based reclaim
        applies only when the PID is dead/unknown."""
        lp = self.index_dir / ".lock"
        # os.getpid() is alive (it's us), and the record is far older than
        # MAX_LOCK_AGE_S — a verified-alive holder must be denied, not reclaimed.
        old_at = time.time() - _lock.MAX_LOCK_AGE_S - 10.0
        lp.write_text(json.dumps({"pid": os.getpid(), "at": old_at}), encoding="utf-8")
        with self.assertRaises(_lock.IndexBusy):
            with _lock.acquire_index_lock(self.index_dir, wait_s=0.0):
                pass
        # untouched — the alive holder's record must survive.
        rec = json.loads(lp.read_text(encoding="utf-8"))
        self.assertEqual(rec["pid"], os.getpid())

    def test_unknown_liveness_holder_older_than_max_age_is_reclaimed(self):
        """The age ceiling still applies when liveness cannot be PROVEN
        (PermissionError from os.kill) — a lock stuck in that ambiguous state
        must still eventually be reclaimable, unlike a verified-alive one."""
        lp = self.index_dir / ".lock"
        old_at = time.time() - _lock.MAX_LOCK_AGE_S - 10.0
        lp.write_text(json.dumps({"pid": os.getpid(), "at": old_at}), encoding="utf-8")

        original = _lock._pid_status
        _lock._pid_status = lambda pid: "unknown"
        try:
            with _lock.acquire_index_lock(self.index_dir, wait_s=0.0) as held:
                self.assertIsNotNone(held)
        finally:
            _lock._pid_status = original
        self.assertFalse(lp.exists())

    def test_ancestor_held_lock_is_not_reacquired_by_the_child(self):
        lp = self.index_dir / ".lock"
        # Simulate another real holder — the re-entrant branch must not touch it.
        lp.write_text(json.dumps({"pid": 999999999, "at": time.time()}), encoding="utf-8")
        os.environ[_lock.ENV_HELD] = "1"
        try:
            with _lock.acquire_index_lock(self.index_dir, wait_s=0.0) as held:
                self.assertIsNone(held)
        finally:
            del os.environ[_lock.ENV_HELD]
        # Untouched: still exactly the simulated holder's record.
        rec = json.loads(lp.read_text(encoding="utf-8"))
        self.assertEqual(rec["pid"], 999999999)

    def test_lock_is_released_when_the_body_raises(self):
        lp = self.index_dir / ".lock"
        with self.assertRaises(ValueError):
            with _lock.acquire_index_lock(self.index_dir, wait_s=0.0):
                self.assertTrue(lp.exists())
                raise ValueError("boom")
        self.assertFalse(lp.exists())

    def test_second_acquirer_without_wait_raises_index_busy(self):
        lp = self.index_dir / ".lock"
        lp.write_text(json.dumps({"pid": os.getpid(), "at": time.time()}), encoding="utf-8")
        with self.assertRaises(_lock.IndexBusy) as ctx:
            with _lock.acquire_index_lock(self.index_dir, wait_s=0.0):
                pass
        self.assertEqual(ctx.exception.pid, os.getpid())


if __name__ == "__main__":
    unittest.main()
