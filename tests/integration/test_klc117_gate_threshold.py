#!/usr/bin/env python3
"""KLC-117 step-5 — AC-9/AC-11/AC-12: the advisory gate signal is threshold-aware.

`gate_policy.collect_signals`'s `advisory` value becomes `{"records": [...],
"threshold": <str>} | None` (D-102: read from the persisted artifact — the one
non-test call site, `core/phases/ack.py`'s `--auto` branch, always runs strictly
after a persisting ack already wrote it). `_CHECK["advisory"]` is clean only when
no record reaches the threshold; absent/unreadable is dirty (fail-closed).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402
import gate_policy  # noqa: E402


def _seed_ticket(tmp_path: Path, ticket: str, phase: str = "build:ack-needed",
                 history: tuple = ()) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "feature", "phase": phase, "track": "M",
           "route_confidence": "high", "affected_modules": ["core/skills"],
           "layer": "code",
           "phase_history": [{"phase": p, "event": "set_state"} for p in history],
           "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3}}
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_advisory_signal_clean_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-G01"
    _seed_ticket(tmp_path, ticket)
    advisories.finish(ticket, "build", [
        ("t", [{"source": "t", "severity": "info", "code": "t.a", "message": "m1", "ref": ""}]),
        ("t", [{"source": "t", "severity": "info", "code": "t.b", "message": "m2", "ref": ""}]),
        ("t", [{"source": "t", "severity": "info", "code": "t.c", "message": "m3", "ref": ""}]),
    ], persist=True)

    sig = gate_policy.collect_signals(ticket, "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is True


def test_advisory_signal_clean_when_zero_records_persisted(tmp_path, monkeypatch):
    """KLC-173: a genuinely clean ack persists nothing; the gate reads the
    missing phase key as CLEAN because the ticket history records the phase
    reaching ack-needed, so `--auto` does not pause on the cleanest ack."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-G01B"
    _seed_ticket(tmp_path, ticket, history=("build:work", "build:ack-needed"))
    records, summary = advisories.finish(ticket, "build", [("t", [])], persist=True)
    assert records == []

    assert not (tmp_path / ".klc" / "tickets" / ticket / "advisories.json").exists()

    sig = gate_policy.collect_signals(ticket, "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is True


def test_advisory_signal_dirty_when_artifact_missing_or_unreadable(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-G02"
    _seed_ticket(tmp_path, ticket)
    # no artifact written at all

    sig = gate_policy.collect_signals(ticket, "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is False


def test_conditional_gate_auto_proceeds_info_only(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-G03"
    _seed_ticket(tmp_path, ticket)
    advisories.finish(ticket, "build", [
        ("t", [{"source": "t", "severity": "info", "code": "t.a", "message": "m1", "ref": ""}]),
    ], persist=True)

    sig = gate_policy.collect_signals(ticket, "build")
    sig.update({"scope_expansion": False, "sentinels": False, "mutation": False,
               "budget_overrun": False, "verdict": "N/A"})
    decision = gate_policy.evaluate("conditional", sig)
    assert decision.proceed is True


def test_conditional_gate_pauses_on_one_high_record(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-G04"
    _seed_ticket(tmp_path, ticket)
    advisories.finish(ticket, "build", [
        ("t", [{"source": "t", "severity": "info", "code": "t.a", "message": "m1", "ref": ""}]),
        ("t", [{"source": "t", "severity": "high", "code": "t.h", "message": "m-high", "ref": ""}]),
    ], persist=True)

    sig = gate_policy.collect_signals(ticket, "build")
    sig.update({"scope_expansion": False, "sentinels": False, "mutation": False,
               "budget_overrun": False, "verdict": "N/A"})
    decision = gate_policy.evaluate("conditional", sig)
    assert decision.proceed is False


def test_decision_gate_still_pauses_with_info_only_records(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-G05"
    _seed_ticket(tmp_path, ticket)
    advisories.finish(ticket, "build", [
        ("t", [{"source": "t", "severity": "info", "code": "t.a", "message": "m1", "ref": ""}]),
    ], persist=True)

    sig = gate_policy.collect_signals(ticket, "build")
    sig.update({"scope_expansion": False, "sentinels": False, "mutation": False,
               "budget_overrun": False, "verdict": "N/A"})
    decision = gate_policy.evaluate("decision", sig)
    assert decision.proceed is False
