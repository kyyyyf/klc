#!/usr/bin/env python3
"""KLC-117 step-1 — AC-3: severity normalisation in `advisories.normalise_record`.

Severity is restricted to high/medium/low/info (spec AC-3). A record offering
any other value, or omitting the field entirely, normalises to `info` AND raises
a companion flag record naming the offender — the mis-declaration must be
visible, not silently swallowed (C-003: severity is never inferred downstream,
so a bad declaration is surfaced, not guessed at).
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402


def test_unknown_severity_normalised_to_info_and_flagged():
    raw = {"source": "test-producer", "severity": "critical", "code": "test.cond",
           "message": "something happened", "ref": "x"}
    rec, flag = advisories.normalise_record("test-producer", raw)

    assert rec["severity"] == "info"
    assert rec["code"] == "test.cond"
    assert rec["message"] == "something happened"

    assert flag is not None
    assert flag["severity"] == "info"
    assert flag["code"] == "malformed-record"
    assert "critical" in flag["message"]
    assert "test.cond" in flag["message"]


def test_missing_severity_field_defaults_to_info_and_flagged():
    raw = {"source": "test-producer", "code": "test.cond2", "message": "no severity given"}
    rec, flag = advisories.normalise_record("test-producer", raw)

    assert rec["severity"] == "info"
    assert rec["code"] == "test.cond2"
    assert rec["message"] == "no severity given"

    assert flag is not None
    assert flag["severity"] == "info"
    assert flag["code"] == "malformed-record"
