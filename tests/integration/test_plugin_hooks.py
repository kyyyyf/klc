#!/usr/bin/env python3
"""Test that the gate hook script blocks advancing past pick_required gates (AC-5).

The hook reads ticket phase via `klc status --json` and blocks when the ticket
is in a pick_required:ack-needed state but no pick has been made.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_DIR = FW_ROOT / "klc-plugin"
HOOK_GATE = PLUGIN_DIR / "hooks" / "gate.py"
SCRIPTS = FW_ROOT / "scripts"
KLC = SCRIPTS / "klc"


def _make_env(project_root: Path) -> dict[str, str]:
    env = {**os.environ, "PROJECT_ROOT": str(project_root)}
    env.pop("KLC_TICKETS_DIR", None)
    # Point KLC_BIN at our scripts/klc so gate.py can call it without PATH deps.
    env["KLC_BIN"] = f"{sys.executable} {KLC}"
    env["KLC_FW_ROOT"] = str(FW_ROOT)
    return env


def _bootstrap_ticket(klc_dir: Path, ticket: str, phase: str,
                      track: str = "M") -> None:
    import json as _j
    tdir = klc_dir / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "kind_source": "user",
        "phase": phase,
        "phase_history": [],
        "track": track,
        "affected_modules": [],
        "estimate": None,
        "jira_url": None,
        "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(_j.dumps(meta), encoding="utf-8")


def test_gate_hook_script_exists() -> None:
    """hooks/gate.py exists in the plugin directory."""
    assert HOOK_GATE.exists(), (
        f"klc-plugin/hooks/gate.py missing — gate hook not implemented"
    )


def test_hooks_json_exists() -> None:
    """hooks/hooks.json exists and is valid JSON."""
    hooks_json = PLUGIN_DIR / "hooks" / "hooks.json"
    assert hooks_json.exists(), "klc-plugin/hooks/hooks.json missing"
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "hooks.json must be a JSON object"
    assert "hooks" in data, "hooks.json must have a 'hooks' key"


def test_gate_block() -> None:
    """Gate hook exits 1 when ticket is in pick_required:ack-needed."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        klc_dir = root / ".klc"
        klc_dir.mkdir()
        # design:ack-needed is pick_required in M track
        _bootstrap_ticket(klc_dir, "T-GATE-001",
                          phase="design:ack-needed", track="M")
        env = _make_env(root)
        env["KLC_TICKET"] = "T-GATE-001"

        result = subprocess.run(
            [sys.executable, str(HOOK_GATE)],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode != 0, (
            "gate hook should block (exit != 0) for pick_required:ack-needed;\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def test_gate_pass() -> None:
    """Gate hook exits 0 when ticket is NOT in pick_required:ack-needed."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        klc_dir = root / ".klc"
        klc_dir.mkdir()
        _bootstrap_ticket(klc_dir, "T-GATE-002",
                          phase="discovery-lite:work", track="S")
        env = _make_env(root)
        env["KLC_TICKET"] = "T-GATE-002"

        result = subprocess.run(
            [sys.executable, str(HOOK_GATE)],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, (
            "gate hook should pass (exit 0) for work state;\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
