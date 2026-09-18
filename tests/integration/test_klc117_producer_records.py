#!/usr/bin/env python3
"""KLC-117 step-2 — AC-1: producers emit structured advisory records.

Drives two real producers — `spec_selfcheck` and `ac_test_coverage` — through
`advisories.collect` over a fixture ticket, and asserts every collected item is
a dict carrying all five required fields. Nothing here is wired into the gate
yet (that is step-3); this only proves the producer-side contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402
import ac_test_coverage as _acov  # noqa: E402
import spec_selfcheck as _ssc  # noqa: E402


def _seed_ticket(tmp_path: Path, ticket: str) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(json.dumps({"ticket": ticket}), encoding="utf-8")
    (tdir / "spec.md").write_text(
        "## Acceptance Criteria\n\n1. AC-1: the widget · renders · the color · when requested\n",
        encoding="utf-8",
    )
    (tdir / "test-plan.md").write_text(
        "## Acceptance coverage\n\nno AC-1 mention here yet.\n", encoding="utf-8",
    )
    return tdir


def test_producers_emit_structured_records(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-TESTFIXTURE"
    _seed_ticket(tmp_path, ticket)

    ssc_report = _ssc.self_check(
        "## Acceptance Criteria\n1. AC-1: the widget · renders the color · fast · when requested\n",
        track="M",
    )
    acov_report = _acov.check(ticket, "S", run_tests=False)

    sources = [
        ("spec-self-check", _ssc.advisory_records(ssc_report)),
        ("ac-coverage", _acov.advisory_records(acov_report)),
    ]
    records = advisories.collect(sources)

    assert records, "expected at least one advisory record from the two producers"
    for rec in records:
        assert isinstance(rec, dict)
        for key in ("source", "severity", "code", "message", "ref"):
            assert key in rec, f"record missing {key!r}: {rec}"
            assert isinstance(rec[key], str)
        assert rec["severity"] in advisories.SEVERITIES
