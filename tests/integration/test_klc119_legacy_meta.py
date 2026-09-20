#!/usr/bin/env python3
"""KLC-119 step-4 — AC-14: every reader of `metrics.tokens` tolerates a meta
with no record and a meta in the pre-KLC-119 single-record shape.
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


def _seed(tmp_path: Path, ticket: str, **extra) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "build:ack", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    meta.update(extra)
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    return tdir


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(KLC), *args],
                          capture_output=True, text=True, env=env)


def test_status_board_rollup_succeed_unchanged_on_meta_with_no_tokens_record(
        tmp_path):
    _seed(tmp_path, "KLC-300")
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("KLC_CARD_ROOT", None)

    r1 = _run(env, "status", "KLC-300")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    r2 = _run(env, "board")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    r3 = _run(env, "metrics", "--rollup")
    assert r3.returncode == 0, r3.stdout + r3.stderr


def test_status_board_rollup_succeed_unchanged_on_pre_klc119_single_record_shape(
        tmp_path):
    _seed(tmp_path, "KLC-301", metrics={
        "tokens": {
            "build": {"in": 100, "out": 20, "cache_hit": 0, "source": "estimated"},
        },
    })
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("KLC_CARD_ROOT", None)

    r1 = _run(env, "status", "KLC-301")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    r2 = _run(env, "board")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    r3 = _run(env, "metrics", "--rollup")
    assert r3.returncode == 0, r3.stdout + r3.stderr


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
