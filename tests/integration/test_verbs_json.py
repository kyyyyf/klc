#!/usr/bin/env python3
"""Test --json output for klc status / next / ack verbs.

These tests spin up a minimal ticket in a temp dir and run the verbs via
subprocess so the full dispatch path is exercised.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = FW_ROOT / "scripts"
KLC = SCRIPTS / "klc"


def _make_env(project_root: Path) -> dict[str, str]:
    env = {**os.environ, "PROJECT_ROOT": str(project_root)}
    env.pop("KLC_TICKETS_DIR", None)
    return env


def _bootstrap_ticket(klc_dir: Path, ticket: str, phase: str = "discovery-lite:work",
                      track: str = "S") -> None:
    """Write a minimal .klc layout for a ticket."""
    tdir = klc_dir / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "kind_source": "user",
        "phase": phase,
        "phase_history": [
            {"phase": "intake:work", "started_at": "2026-01-01T00:00:00Z",
             "ended_at": "2026-01-01T01:00:00Z"},
        ],
        "track": track,
        "affected_modules": [],
        "estimate": None,
        "jira_url": None,
        "created": "2026-01-01T00:00:00Z",
    }
    import json as _j
    (tdir / "meta.json").write_text(_j.dumps(meta), encoding="utf-8")


def test_status_json() -> None:
    """klc status <ticket> --json emits valid JSON with phase and track."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        klc_dir = root / ".klc"
        klc_dir.mkdir()
        _bootstrap_ticket(klc_dir, "T-JSON-001")
        env = _make_env(root)

        result = subprocess.run(
            [sys.executable, str(KLC), "status", "T-JSON-001", "--json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )
        data = json.loads(result.stdout)
        assert "phase" in data, f"JSON missing 'phase': {data}"
        assert "track" in data, f"JSON missing 'track': {data}"
        assert data["track"] == "S"
        assert "discovery-lite" in data["phase"]


def test_next_ack_json() -> None:
    """klc next --json and klc ack --json report the transition in JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        klc_dir = root / ".klc"
        klc_dir.mkdir()
        env = _make_env(root)

        # ack test: start from ack-needed (no pick required for intake)
        _bootstrap_ticket(klc_dir, "T-JSON-002", phase="intake:ack-needed", track="S")
        result = subprocess.run(
            [sys.executable, str(KLC), "ack", "T-JSON-002", "--pick", "1", "--json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, (
            f"ack --json failed (exit {result.returncode})\nstderr: {result.stderr}"
        )
        data = json.loads(result.stdout)
        assert "phase" in data, f"ack JSON missing 'phase': {data}"

        # next test: start a separate ticket from :ack so next can advance it
        _bootstrap_ticket(klc_dir, "T-JSON-003", phase="discovery-lite:ack", track="S")
        result2 = subprocess.run(
            [sys.executable, str(KLC), "next", "T-JSON-003", "--json"],
            capture_output=True, text=True, env=env,
        )
        assert result2.returncode == 0, (
            f"next --json failed (exit {result2.returncode})\nstderr: {result2.stderr}"
        )
        data2 = json.loads(result2.stdout)
        assert "phase" in data2, f"next JSON missing 'phase': {data2}"


def test_status_json_error_path() -> None:
    """klc status --json on unknown ticket returns exit 1 (no bare traceback)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".klc").mkdir()
        env = _make_env(root)

        result = subprocess.run(
            [sys.executable, str(KLC), "status", "T-MISSING", "--json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode != 0
        # Should NOT be a Python traceback
        assert "Traceback" not in result.stderr, (
            f"Got bare traceback: {result.stderr}"
        )
