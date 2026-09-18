#!/usr/bin/env python3
"""KLC-117 — `advisories.render_summary` (AC-6, AC-7).

step-1: the summary line's per-severity counts and rendering rule (D-003: high
and medium always render, low/info only when non-zero).

step-3 adds the gate-level empty-result assertion once `can_complete` routes
through the aggregator.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402
import phase_completion as _pc  # noqa: E402


def test_summary_counts_and_path_when_records_exist():
    records = (
        [{"source": "s", "severity": "high", "code": "s.h", "message": "m", "ref": ""}]
        + [{"source": "s", "severity": "medium", "code": "s.m", "message": "m", "ref": ""}] * 2
        + [{"source": "s", "severity": "info", "code": "s.i", "message": "m", "ref": ""}] * 3
    )

    summary = advisories.render_summary(records, "tickets/KLC-999/build/ack-advisories.json")

    assert summary == "1 high · 2 medium · 3 info — see tickets/KLC-999/build/ack-advisories.json"


def test_empty_advisory_result_when_no_producer_emits(tmp_path, monkeypatch):
    """AC-7 (gate level): no producer emits anything → `can_complete_build`
    returns `(True, "")` — no special-cased empty-state text."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import ac_test_coverage as acov

    tdir = tmp_path / ".klc" / "tickets" / "KLC-EMPTY"
    tdir.mkdir(parents=True)
    (tdir / "build-log.md").write_text(
        "# build log\n\n## Evidence\n\n```\n$ true\nok\n```\n", encoding="utf-8")
    (tdir / "meta.json").write_text('{"ticket": "KLC-EMPTY", "track": "M"}', encoding="utf-8")
    (tdir / "impl-plan.md").write_text(
        "# Implementation plan — KLC-EMPTY\n", encoding="utf-8")

    monkeypatch.setattr(_pc, "_impl_plan_steps", lambda d: [])
    monkeypatch.setattr(acov, "check", lambda *a, **k: acov.Report(track="M"))

    ok, msg = _pc.can_complete_build("KLC-EMPTY", persist=True)
    assert ok is True
    assert msg == ""
