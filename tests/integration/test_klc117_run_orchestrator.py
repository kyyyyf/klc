#!/usr/bin/env python3
"""KLC-117 step-6 — AC-14: the orchestrator-facing gate signal is threshold-aware,
not string-non-emptiness-aware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402
import gate_policy  # noqa: E402


def test_gate_policy_signal_survives_nonempty_summary_string(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-RO01"
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
           "track": "M", "route_confidence": "high",
           "affected_modules": ["core/skills"], "layer": "code",
           "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3}}
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    records, summary = advisories.finish(ticket, "build", [
        ("s", [{"source": "s", "severity": "info", "code": "s.a", "message": "m1", "ref": ""}]),
        ("s", [{"source": "s", "severity": "info", "code": "s.b", "message": "m2", "ref": ""}]),
        ("s", [{"source": "s", "severity": "info", "code": "s.c", "message": "m3", "ref": ""}]),
    ], persist=True)
    assert summary  # non-empty: "0 high · 0 medium · 3 info — see <path>"

    sig = gate_policy.collect_signals(ticket, "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is True
