#!/usr/bin/env python3
"""KLC-173 step-4 — AC-8: drift_check.write_report persists nothing."""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import drift_check as dc  # noqa: E402


def test_write_report_persists_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc" / "tickets" / "KLC-D1"
    tdir.mkdir(parents=True)
    monkeypatch.setattr(dc, "_scope_compare",
                        lambda t: {"drifted_modules": [], "orphan_files": [], "skipped": None})
    monkeypatch.setattr(dc, "_read_impl_plan", lambda t: "")
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    rep = dc.write_report("KLC-D1")
    assert rep["summary"].startswith("drift-check KLC-D1:")
    assert "scope_drift" in rep and "write_error" not in rep
    assert list(tdir.iterdir()) == []
