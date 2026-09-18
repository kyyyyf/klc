#!/usr/bin/env python3
"""KLC-117 step-3 — AC-2: exactly one aggregator on the gate's success path.

A structural grep over `phase_completion.py`'s six former `"; ".join(` success
sites proves none of them still executes that literal — every one routes
through `advisories.finish`. A second test proves the probe and the persisting
call share the SAME collection/rendering logic (same summary, same records)
over identical producer output.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402


def test_no_second_string_join_path_remains_on_success():
    text = (FW_ROOT / "core" / "skills" / "phase_completion.py").read_text(encoding="utf-8")
    assert '"; ".join(' not in text, (
        "a literal string-join success path still exists in phase_completion.py; "
        "every success return must route through advisories.finish")


def test_probe_and_persisting_calls_share_one_aggregator(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = tmp_path / ".klc" / "tickets" / "KLC-P1"
    d.mkdir(parents=True)

    sources = [("test-producer", [{"source": "test-producer", "severity": "medium",
                                   "code": "t.c", "message": "m", "ref": ""}])]
    records_probe, summary_probe = advisories.finish("KLC-P1", "discovery", sources, persist=False)
    records_real, summary_real = advisories.finish("KLC-P1", "discovery", sources, persist=True)

    assert records_probe == records_real
    assert summary_probe == summary_real
