#!/usr/bin/env python3
"""KLC-117 — degrade-not-fail paths of `advisories.collect` (C-001).

step-1: a bare string (an old-shaped, not-yet-converted producer) and a
malformed dict (missing required keys) each degrade to exactly one `info`
record naming the offending producer, rather than being forwarded verbatim or
crashing collection.

step-3 adds the raising-producer case, once `advisories.finish`/`can_complete`
exist to drive it end-to-end.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402
import phase_completion as _pc  # noqa: E402


def test_bare_string_producer_wrapped_as_legacy_string_info_record():
    records = advisories.collect([("legacy-producer", ["a plain string advisory"])])

    assert len(records) == 1
    rec = records[0]
    assert rec["source"] == "legacy-producer"
    assert rec["severity"] == "info"
    assert rec["code"] == "legacy-string"
    assert rec["message"] == "a plain string advisory"


def test_record_missing_required_keys_degrades_to_info():
    # No `message` at all — the aggregator must not drop it silently.
    records = advisories.collect([("bad-producer", [{"source": "bad-producer"}])])

    assert len(records) == 1
    rec = records[0]
    assert rec["source"] == "bad-producer"
    assert rec["severity"] == "info"
    assert rec["code"] == "malformed-record"
    assert "bad-producer" in rec["message"]


def test_raising_producer_degrades_to_single_info_record(tmp_path, monkeypatch):
    """AC-18 (gate level, C-001): a producer raises inside the gate's collection —
    the ack still completes, and exactly one info record names the offender."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import ac_test_coverage as acov

    tdir = tmp_path / ".klc" / "tickets" / "KLC-BOOM"
    tdir.mkdir(parents=True)
    (tdir / "build-log.md").write_text(
        "# build log\n\n## Evidence\n\n```\n$ true\nok\n```\n", encoding="utf-8")
    (tdir / "meta.json").write_text('{"ticket": "KLC-BOOM", "track": "M"}', encoding="utf-8")
    (tdir / "impl-plan.md").write_text(
        "# Implementation plan — KLC-BOOM\n", encoding="utf-8")

    monkeypatch.setattr(_pc, "_impl_plan_steps", lambda d: [])
    import step_state  # KLC-174: step gate is covered in test_klc174_build_ack.py
    monkeypatch.setattr(step_state, "check_build", lambda *a, **k: (True, ""))

    def _boom(*a, **k):
        raise RuntimeError("coverage exploded")

    monkeypatch.setattr(acov, "check", _boom)

    ok, msg = _pc.can_complete_build("KLC-BOOM", persist=True)
    assert ok is True, "a raising producer must never block the ack"
    assert msg  # a non-empty summary — one record was collected

    envelope = advisories.read("KLC-BOOM", "build")
    assert envelope is not None
    assert len(envelope["records"]) == 1
    rec = envelope["records"][0]
    assert rec["source"] == "ac-coverage"
    assert rec["severity"] in ("info", "medium")
    assert "ac-coverage" in rec["message"]
