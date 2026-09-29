"""KLC-136 step-8 — AC-3 follow-on (found by the operator's AC-9
PROJECT_ROOT-unset full-suite run, 2026-09-29): five test modules
(`test_jira_core.py`, `test_jira_pull.py`, `test_jira_managed.py`,
`test_step_card_compression.py`, `test_klc113_step_card_fields.py`) each
carried a bare module-level `os.environ.setdefault("PROJECT_ROOT", ...)`.
Unlike `monkeypatch.setenv`, a plain module-level assignment is never
undone — once one of these modules is COLLECTED, its scratch default leaks
into every later test for the rest of the pytest PROCESS. That is exactly
what corrupted `test_klc136_guard.py::test_guard_watches_all_three_roots`'s
`_paths.project_root()` reading in the operator's unset-PROJECT_ROOT full
run: `real_roots` (the plugin's session-start snapshot) disagreed with
`expected` (recomputed from the CURRENT, by-then-leaked `project_root()`)
by exactly one of these five modules' scratch prefix
(`/tmp/klc-jira-test-<x>`).

Real-substrate: this drives a genuine inner pytest subprocess collecting
the five real modules, not a mock.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_FORMERLY_LEAKING_MODULES = [
    "tests/integration/test_jira_core.py",
    "tests/integration/test_jira_pull.py",
    "tests/integration/test_jira_managed.py",
    "tests/integration/test_step_card_compression.py",
    "tests/integration/test_klc113_step_card_fields.py",
]

_CANARY_SRC = '''
import os

def test_canary_sees_no_leaked_project_root():
    assert "PROJECT_ROOT" not in os.environ, os.environ.get("PROJECT_ROOT")
'''


def test_no_module_leaks_project_root_past_its_own_tests(tmp_path):
    """AC-3 follow-on: with PROJECT_ROOT UNSET at the start, running each of
    the five formerly-leaking modules followed by a canary must leave
    PROJECT_ROOT unset again — the canary must never see a leaked
    `klc-jira-test-`/`klc-jira-pull-`/`klc-jira-managed-`/`klc-test-`/
    `klc-t113-test-` scratch default."""
    canary_dir = tmp_path / "canary"
    canary_dir.mkdir()
    canary = canary_dir / "test_canary.py"
    canary.write_text(_CANARY_SRC, encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if k != "PROJECT_ROOT"}
    cmd = [sys.executable, "-m", "pytest", *_FORMERLY_LEAKING_MODULES, str(canary),
           "-q", "-p", "no:cacheprovider"]
    r = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env,
                       capture_output=True, text=True, timeout=100)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
