"""KLC-172 step-2: explicit planning-reviewer roles and the optional `effort` knob."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW / "core" / "skills"))

import models  # noqa: E402
import runner  # noqa: E402

REVIEWERS = ("spec-reviewer", "test-plan-reviewer", "impl-plan-reviewer",
             "drift-reviewer")


def _argv_for(monkeypatch, resolved):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setenv("CLAUDE_CLI", "claude")
    monkeypatch.setattr(runner.shutil, "which", lambda b: "/usr/bin/" + b)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner._dispatch_anthropic(resolved, "prompt", 5, {})
    return seen["argv"]


def test_reviewer_roles_explicit_and_effort_flag(monkeypatch):
    m = models.load_models(force=True)
    for phase in REVIEWERS:
        assert phase in m.phase_roles, phase
        r = m.resolve(phase)
        assert r.source == "phase_roles" and r.model

    high = m.resolve("discovery")  # heavy-reasoning
    assert high.effort == "high"
    argv = _argv_for(monkeypatch, high)
    assert argv[argv.index("--effort") + 1] == "high"
    assert ["--effort", "high"] == argv[argv.index("--effort"):argv.index("--effort") + 2]

    plain = m.resolve("build")
    assert plain.effort is None
    assert "--effort" not in _argv_for(monkeypatch, plain)
