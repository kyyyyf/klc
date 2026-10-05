#!/usr/bin/env python3
"""KLC-117 step-6 — AC-13: `klc status` print high+medium records in
full and a bare count of the rest, reading the persisted artifact only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = FW_ROOT / "scripts"
KLC = SCRIPTS / "klc"


def _make_env(project_root: Path) -> dict[str, str]:
    env = {**os.environ, "PROJECT_ROOT": str(project_root)}
    env.pop("KLC_TICKETS_DIR", None)
    return env


def _bootstrap(tmp_path: Path, ticket: str) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": "build:ack-needed",
        "phase_history": [
            {"phase": "build:work", "started_at": "2026-01-01T00:00:00Z"},
        ],
        "track": "M", "affected_modules": ["core/skills"], "estimate": None,
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    build_dir = tdir / "build"
    build_dir.mkdir()
    records = (
        [{"source": "s", "severity": "high", "code": f"s.h{i}",
          "message": f"high finding {i}", "ref": ""} for i in range(2)]
        + [{"source": "s", "severity": "medium", "code": "s.m0",
            "message": "medium finding", "ref": ""}]
        + [{"source": "s", "severity": "info", "code": f"s.i{i}",
            "message": f"info {i}", "ref": ""} for i in range(9)]
    )
    envelope = {"schema_version": 1, "ticket": ticket, "phase": "build",
               "generated_at": "2026-01-01T00:00:00Z", "records": records}
    (tdir / "advisories.json").write_text(json.dumps({"build": envelope}), encoding="utf-8")


def test_status_json_prints_high_medium_in_full_and_counts_remainder(tmp_path):
    ticket = "KLC-SW01"
    _bootstrap(tmp_path, ticket)
    env = _make_env(tmp_path)
    result = subprocess.run(
        [sys.executable, str(KLC), "status", ticket, "--json"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    adv = data["advisories"]
    assert len(adv["high"]) == 2
    assert len(adv["medium"]) == 1
    assert adv["other_count"] == 9
