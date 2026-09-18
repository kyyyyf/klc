#!/usr/bin/env python3
"""KLC-107 step-4/step-5 — index_refresh: the freshness seam, budgeted by a
process-tree kill (findings F-1's verb-side half, F-2 / [!DECISION D-202]);
and its wiring into `klc intake`, `klc next` and `klc ack` (step-5).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
PHASES_DIR = FRAMEWORK_ROOT / "core" / "phases"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(PHASES_DIR))
import index_refresh as _refresh  # noqa: E402
import index_lock as _lock  # noqa: E402

INIT = FRAMEWORK_ROOT / "scripts" / "init.py"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
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
    r = subprocess.run([sys.executable, str(INIT), "--scan-only"],
                       cwd=str(root), env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    return root


def _advance_head(root: Path) -> None:
    (root / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "advance")


_HOLDER_SRC = """
import sys, time
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


class TestLazyRefreshSkipped(unittest.TestCase):
    def test_lazy_refresh_skipped_when_last_run_equals_head(self):
        """AC-10: .last-run == HEAD already — zero spawns, zero lock files."""
        with tempfile.TemporaryDirectory(prefix="klc-test-klc107-refresh-") as td:
            root = _make_repo(Path(td))
            with mock.patch.object(_refresh, "_spawn") as spawn:
                out = mock.Mock()
                result = _refresh.refresh_if_stale(root, out=out)
            self.assertEqual(result["status"], "fresh")
            spawn.assert_not_called()
            self.assertFalse((root / ".klc" / "index" / ".lock").exists())


class TestSuppression(unittest.TestCase):
    def test_no_index_refresh_flag_and_env_var_suppress_refresh(self):
        """AC-11: the flag alone, the env var alone, and both together each
        suppress; one line states so; .last-run unchanged."""
        with tempfile.TemporaryDirectory(prefix="klc-test-klc107-refresh-") as td:
            root = _make_repo(Path(td))
            _advance_head(root)
            last_before = (root / ".klc" / "index" / ".last-run").read_text(encoding="utf-8")

            # flag alone
            out = mock.Mock()
            with mock.patch.object(_refresh, "_spawn") as spawn:
                r = _refresh.refresh_if_stale(root, suppressed=True, out=out)
            self.assertEqual(r["status"], "suppressed")
            spawn.assert_not_called()
            self.assertIn("suppressed", out.write.call_args[0][0])

            # env var alone
            os.environ["KLC_NO_INDEX_REFRESH"] = "1"
            try:
                out2 = mock.Mock()
                with mock.patch.object(_refresh, "_spawn") as spawn2:
                    r2 = _refresh.refresh_if_stale(root, out=out2)
                self.assertEqual(r2["status"], "suppressed")
                spawn2.assert_not_called()

                # both together — no double-suppress error
                out3 = mock.Mock()
                r3 = _refresh.refresh_if_stale(root, suppressed=True, out=out3)
                self.assertEqual(r3["status"], "suppressed")
            finally:
                del os.environ["KLC_NO_INDEX_REFRESH"]

            last_after = (root / ".klc" / "index" / ".last-run").read_text(encoding="utf-8")
            self.assertEqual(last_before, last_after)


class TestBusyLock(unittest.TestCase):
    def test_refresh_skipped_while_another_writer_holds_the_index_lock(self):
        """AC-10/AC-11 supporting behaviour: a second real writer holds the
        lock; the helper returns status busy within its two-second wait,
        prints one line naming the holding PID, spawns zero builders, and
        never raises (finding F-1's verb-side half)."""
        with tempfile.TemporaryDirectory(prefix="klc-test-klc107-refresh-") as td:
            root = _make_repo(Path(td))
            _advance_head(root)
            index_dir = root / ".klc" / "index"
            ready = root / "_holder_ready"
            holder = _spawn_holder(index_dir, ready, hold_s=5.0)
            try:
                _wait_for(ready)
                out = mock.Mock()
                with mock.patch.object(_refresh, "_spawn") as spawn:
                    started = time.monotonic()
                    result = _refresh.refresh_if_stale(root, out=out)
                    elapsed = time.monotonic() - started
                self.assertEqual(result["status"], "busy")
                self.assertLess(elapsed, _refresh.LOCK_WAIT_S + 2.0)
                spawn.assert_not_called()
                msg = out.write.call_args[0][0]
                self.assertIn("PID", msg)
            finally:
                holder.terminate()
                holder.communicate(timeout=10)


def _write_stub(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")


class TestBudgetKillsProcessTree(unittest.TestCase):
    """Finding F-2 / [!DECISION D-202]: the budget kills the whole process
    tree the refresh spawned, not merely the direct child."""

    def test_refresh_terminated_at_wall_clock_budget_kills_the_whole_process_tree(self):
        with tempfile.TemporaryDirectory(prefix="klc-test-klc107-refresh-") as td:
            root = _make_repo(Path(td))
            _advance_head(root)
            stub = Path(td) / "hanging_update_stub.py"
            gc_pidfile = Path(td) / "grandchild.pid"
            _write_stub(stub, f"""
                import subprocess, sys, time
                gc = subprocess.Popen([sys.executable, "-c",
                    "import time; time.sleep(300)"])
                with open({str(gc_pidfile)!r}, "w") as fh:
                    fh.write(str(gc.pid))
                time.sleep(300)
            """)
            out = mock.Mock()
            with mock.patch.object(_refresh, "_UPDATE_SCRIPT", stub):
                result = _refresh.refresh_if_stale(root, budget_s=0.5, out=out)
            self.assertEqual(result["status"], "timeout")

            _wait_for(gc_pidfile, timeout_s=10.0)
            gc_pid = int(gc_pidfile.read_text(encoding="utf-8").strip())
            time.sleep(0.3)  # let the SIGKILL actually land
            self.assertFalse(_pid_alive(gc_pid), "grandchild survived the budget kill")

    def test_refresh_within_budget_completes_normally(self):
        """Boundary-adjacent pair: a stub that finishes comfortably inside
        the budget is NOT terminated."""
        with tempfile.TemporaryDirectory(prefix="klc-test-klc107-refresh-") as td:
            root = _make_repo(Path(td))
            _advance_head(root)
            stub = Path(td) / "quick_update_stub.py"
            _write_stub(stub, """
                import time
                time.sleep(0.1)
            """)
            out = mock.Mock()
            with mock.patch.object(_refresh, "_UPDATE_SCRIPT", stub):
                result = _refresh.refresh_if_stale(root, budget_s=5.0, out=out)
            self.assertEqual(result["status"], "refreshed")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class TestRefreshFailureNeverRaises(unittest.TestCase):
    """AC-13: a refresh that exits non-zero or raises never propagates, and
    the failing step is named on stderr."""

    def test_refresh_exit_nonzero_returns_status_dict(self):
        """AC-13: a refresh that exits non-zero never changes the verb exit code."""
        with tempfile.TemporaryDirectory(prefix="klc-test-klc107-refresh-") as td:
            root = _make_repo(Path(td))
            _advance_head(root)
            stub = Path(td) / "failing_update_stub.py"
            _write_stub(stub, """
                import sys
                sys.stderr.write("stub deliberately failing\\n")
                sys.exit(1)
            """)
            out = mock.Mock()
            with mock.patch.object(_refresh, "_UPDATE_SCRIPT", stub):
                result = _refresh.refresh_if_stale(root, budget_s=10.0, out=out)
            self.assertEqual(result["status"], "failed")
            self.assertIn("stub deliberately failing", result["detail"])
            msg = out.write.call_args[0][0]
            self.assertIn("scripts/update.py", msg)

    def test_refresh_spawn_raising_returns_status_dict_without_propagating(self):
        """AC-13: a refresh that raises never propagates or changes the exit code."""
        with tempfile.TemporaryDirectory(prefix="klc-test-klc107-refresh-") as td:
            root = _make_repo(Path(td))
            _advance_head(root)
            out = mock.Mock()
            with mock.patch.object(_refresh, "_spawn", side_effect=OSError("boom")):
                result = _refresh.refresh_if_stale(root, budget_s=10.0, out=out)
            self.assertEqual(result["status"], "failed")
            msg = out.write.call_args[0][0]
            self.assertIn("boom", msg)


# --------------------------------------------------------------------------- #
# step-5 — wired into intake / next / ack
# --------------------------------------------------------------------------- #

def _meta(ticket: str, *, phase: str, track: str = "M") -> dict:
    return {
        "ticket": ticket, "kind": "tech", "kind_source": "user", "phase": phase,
        "phase_history": [], "track": track, "route_hint": track,
        "route_confidence": "high", "affected_modules": [], "estimate": None,
        "layer": "code", "budgets": {"mutation_fix_attempts": 0},
        "jira_url": None,
        "created": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _seed_ticket(root: Path, ticket: str, *, phase: str, track: str = "M") -> Path:
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "meta.json").write_text(
        json.dumps(_meta(ticket, phase=phase, track=track), indent=2) + "\n",
        encoding="utf-8")
    return tdir


class TestVerbWiring(unittest.TestCase):
    """AC-7/AC-8/AC-9: `klc intake`, `klc next` and `klc ack` refresh the
    index themselves before they touch ticket state; AC-11's flag half
    exercised through the real verbs, not the helper."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="klc-test-klc107-verbs-")
        self.root = _make_repo(Path(self._td.name))
        _advance_head(self.root)
        self._old_project_root = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = str(self.root)
        self._old_intake_triage = os.environ.get("KLC_INTAKE_TRIAGE")
        os.environ["KLC_INTAKE_TRIAGE"] = "0"

    def tearDown(self):
        if self._old_project_root is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._old_project_root
        if self._old_intake_triage is None:
            os.environ.pop("KLC_INTAKE_TRIAGE", None)
        else:
            os.environ["KLC_INTAKE_TRIAGE"] = self._old_intake_triage
        self._td.cleanup()

    def _head(self) -> str:
        r = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"],
                           capture_output=True, text=True)
        return r.stdout.strip()

    def _last_run(self) -> str:
        p = self.root / ".klc" / "index" / ".last-run"
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""

    def test_intake_refreshes_index_before_writing_ticket_artifact(self):
        import intake as _intake
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = _intake.run(["KLC-9001", "a small refresh-wiring test ticket"])
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / ".klc" / "tickets" / "KLC-9001" / "meta.json").exists())
        self.assertEqual(self._last_run(), self._head())
        self.assertIn("refreshed", buf.getvalue())

    def test_next_refreshes_index_before_computing_next_phase(self):
        import next as _next_verb
        _seed_ticket(self.root, "KLC-9002", phase="discovery:ack")
        _next_verb.run(["KLC-9002"])
        self.assertEqual(self._last_run(), self._head())

    def test_ack_refreshes_index_before_evaluating_gate(self):
        import ack as _ack_verb
        _seed_ticket(self.root, "KLC-9003", phase="discovery:ack-needed")
        _ack_verb.run(["KLC-9003"])
        self.assertEqual(self._last_run(), self._head())

    def test_no_index_refresh_flag_suppresses_refresh_through_the_real_verbs(self):
        import intake as _intake
        last_before = self._last_run()
        rc = _intake.run(["--no-index-refresh", "KLC-9004",
                          "a suppressed refresh test ticket"])
        self.assertEqual(rc, 0)
        self.assertEqual(self._last_run(), last_before)
        self.assertNotEqual(self._last_run(), self._head())


if __name__ == "__main__":
    unittest.main()
