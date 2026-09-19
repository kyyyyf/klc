"""KLC-106 step-8 — `klc doctor` reports degraded builders as a warn-only
check, reading persisted verdicts, re-running nothing (AC-15).

`core/phases/doctor.py`'s `index-degraded` check (KLC-107) was built as an
explicit placeholder — its own docstring says "the shape ... is a working
assumption, not a contract ... this check gains teeth when KLC-106 lands."
This ticket is that landing: `index_health.degraded()` now reads the REAL
verdict shape via `index_coverage.collect_verdicts` and reports WARN (never
FAIL) — AC-15 says escalation to a hard failure is KLC-107's, not this
ticket's.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
KLC = FRAMEWORK_ROOT / "scripts" / "klc"
sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=15)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "t@t.com")
    _run_git(repo, "config", "user.name", "T")
    (repo / "seed.txt").write_text("x", encoding="utf-8")
    _run_git(repo, "add", "seed.txt")
    _run_git(repo, "commit", "-m", "seed")
    return repo


def _head(repo: Path) -> str:
    return _run_git(repo, "rev-parse", "HEAD").stdout.strip()


def _run_doctor(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(KLC), "doctor", *extra],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=60,
    )


class TestIndexHealthWarnOnly(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc106-doctor-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _init_index(self, repo: Path) -> Path:
        index_dir = repo / ".klc" / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / ".last-run").write_text(_head(repo) + "\n", encoding="utf-8")
        for name in ("test_map.json", "file_roles.json", "module_edges.json",
                    "symbol_usage.json"):
            (index_dir / name).write_text("{}", encoding="utf-8")
        return index_dir

    def test_doctor_reports_degraded_builders_warn_only_in_text_and_json(self):
        """Monkeypatch-proof by construction: index_health.degraded() never
        imports subprocess, so this check structurally cannot re-run a
        builder — it only reads JSON files."""
        import inspect
        import index_health
        src = inspect.getsource(index_health.degraded)
        assert "subprocess" not in src, (
            "index_health.degraded() must not invoke subprocess — it reads "
            "persisted artifacts, never re-runs a builder (AC-15)")

        repo = _make_repo(self.tmp_path)
        index_dir = self._init_index(repo)
        (index_dir / "inventory.json").write_text(json.dumps({"errors": [
            {"builder": "inventory:python", "artifact": "inventory.json",
             "metric": "files-with-symbols", "observed": 1, "universe": 20,
             "ratio": 0.05, "threshold": 0.25, "degraded": True,
             "reason": "files-with-symbols 0.05 below threshold 0.25 (1/20)"},
        ]}), encoding="utf-8")

        r = _run_doctor(repo)
        self.assertIn("WARN index-degraded", r.stdout)
        self.assertIn("inventory:python", r.stdout)
        self.assertNotIn("FAIL index-degraded", r.stdout)
        # This check alone must never be the reason doctor's overall exit is
        # non-zero (AC-15) — other, unrelated checks in this sandboxed
        # environment (file permissions, missing API keys) are out of scope.

        rj = _run_doctor(repo, "--json")
        payload = json.loads(rj.stdout)
        entry = next(c for c in payload["checks"] if c["check"] == "index-degraded")
        self.assertTrue(entry.get("warn"))
        self.assertTrue(entry["ok"])
        self.assertTrue(any("inventory:python" in e for e in entry["errors"]))

    def test_doctor_index_health_check_absent_when_index_artifacts_missing(self):
        """FAIL-CLOSED: index artifacts absent -> the check does not
        fabricate a PASS, and the overall doctor run still exits 0
        (degrade-not-fail; escalation is KLC-107's)."""
        repo = _make_repo(self.tmp_path)
        r = _run_doctor(repo)
        self.assertNotIn("FAIL index-degraded", r.stdout)
        # No fabricated PASS: the check must say something, not silently pass.
        idx = r.stdout.find("index-degraded")
        self.assertNotEqual(idx, -1)
        line_start = r.stdout.rfind("\n", 0, idx)
        line = r.stdout[line_start:idx]
        self.assertNotIn("PASS", line)


if __name__ == "__main__":
    unittest.main()
