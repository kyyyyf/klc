#!/usr/bin/env python3
"""KLC-120 step-2 — AC-12: the `klc doctor` `external-reviewer-key` check
warns when the resolved external-reviewer route needs something this host
doesn't have (an unset API key for `openai`/`google`, or a missing `claude`
CLI for `anthropic`), and stays silent otherwise. Runs `klc doctor --json`
as a real subprocess, following tests/integration/test_doctor_integration.py's
fixture pattern, and asserts on the `external-reviewer-key` entry only —
no real API key or real `claude` binary is used anywhere."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]

_OPENAI_MODELS_YML = """\
version: 1
defaults:
  provider: anthropic
  model: claude-sonnet-5
  api_key_env: ANTHROPIC_API_KEY

roles:
  external:
    provider: openai
    model: gpt-4o
    api_key_env: OPENAI_API_KEY

phase_roles:
  review-external: external

per_track: {}
"""


def _make_project(tmp_path: Path, *, openai_override: bool) -> Path:
    project_root = tmp_path / "proj"
    klc = project_root / ".klc"
    (klc / "index").mkdir(parents=True)
    (klc / "config").mkdir(parents=True)
    (klc / "logs").mkdir(parents=True)
    shutil.copy(FW_ROOT / "config" / "phases.yml", klc / "config" / "phases.yml")
    if openai_override:
        (klc / "config" / "models.yml").write_text(_OPENAI_MODELS_YML,
                                                    encoding="utf-8")
    else:
        shutil.copy(FW_ROOT / "config" / "models.yml", klc / "config" / "models.yml")
    (klc / "config" / "profile.yml").write_text("profile: generic\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=str(project_root), capture_output=True,
                   check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(project_root),
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=str(project_root), capture_output=True)
    return project_root


def _run_doctor(project_root: Path, env_overrides: dict, *, clear: tuple = ()) -> dict:
    env = dict(os.environ)
    for k in clear:
        env.pop(k, None)
    env["PROJECT_ROOT"] = str(project_root)
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, str(FW_ROOT / "scripts" / "klc"), "doctor", "--json"],
        cwd=str(project_root), env=env, capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    return next(c for c in payload["checks"] if c["check"] == "external-reviewer-key")


def test_doctor_warns_when_resolved_provider_is_openai_and_key_unset(tmp_path):
    """AC-12 positive: resolved provider `openai`, $OPENAI_API_KEY unset —
    warns."""
    project_root = _make_project(tmp_path, openai_override=True)
    entry = _run_doctor(project_root, {}, clear=("OPENAI_API_KEY", "ANTHROPIC_API_KEY"))
    assert entry.get("warn") is True
    assert any("openai" in e and "OPENAI_API_KEY" in e for e in entry["errors"])


def test_doctor_warns_when_resolved_provider_is_anthropic_and_claude_cli_absent(tmp_path):
    """AC-12 negative / fail-closed twin: resolved provider `anthropic`
    (the default route), no `claude` on PATH — warns."""
    project_root = _make_project(tmp_path, openai_override=False)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    entry = _run_doctor(project_root, {"PATH": str(empty_bin)})
    assert entry.get("warn") is True
    assert any("claude" in e and "PATH" in e for e in entry["errors"])


def test_doctor_silent_when_resolved_provider_is_anthropic_and_claude_cli_present(tmp_path):
    """Fail-closed's positive complement: fake `claude` on PATH — no
    warning is emitted, confirming the check does not spuriously fire once
    the gate scope narrows."""
    project_root = _make_project(tmp_path, openai_override=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "claude"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    entry = _run_doctor(
        project_root, {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"})
    assert not entry.get("warn")
    assert entry["errors"] == []


def test_doctor_silent_for_openai_route_with_key_set(tmp_path):
    """Mirror silent branch (test-plan-review F-2): resolved provider
    `openai` with $OPENAI_API_KEY set — silent, matching AC-10's three-case
    matrix."""
    project_root = _make_project(tmp_path, openai_override=True)
    entry = _run_doctor(project_root, {"OPENAI_API_KEY": "fake-value-for-test"})
    assert not entry.get("warn")
    assert entry["errors"] == []


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
