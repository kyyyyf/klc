#!/usr/bin/env python3
"""KLC-173 step-4 — AC-5/AC-6: one phase-keyed advisories.json per ticket."""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402
import gate_policy  # noqa: E402

REC = {"source": "t", "severity": "high", "code": "t.c", "message": "m", "ref": ""}


def _seed(tmp_path: Path, ticket: str, history=()) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
            "track": "M", "route_confidence": "high",
            "affected_modules": ["core/skills"], "layer": "code",
            "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1,
                         "manual": 0, "total": 3},
            "phase_history": [{"phase": p, "event": "set_state"} for p in history]}
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return tdir


def test_finish_writes_one_keyed_file_and_none_when_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed(tmp_path, "KLC-S1")
    advisories.finish("KLC-S1", "build", [("t", [REC])], persist=True)
    advisories.finish("KLC-S1", "design", [("t", [REC])], persist=True)
    doc = json.loads((tdir / "advisories.json").read_text(encoding="utf-8"))
    assert set(doc) == {"build", "design"}
    assert doc["build"]["records"][0]["code"] == "t.c"
    assert "generated_at" in doc["build"]
    assert not (tdir / "build").exists()

    # a clean re-ack drops only that phase's stale key
    advisories.finish("KLC-S1", "build", [("t", [])], persist=True)
    doc = json.loads((tdir / "advisories.json").read_text(encoding="utf-8"))
    assert set(doc) == {"design"}
    advisories.finish("KLC-S1", "design", [("t", [])], persist=True)
    assert not (tdir / "advisories.json").exists()


def test_clean_ack_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed(tmp_path, "KLC-S2")
    advisories.finish("KLC-S2", "review", [("t", [])], persist=True)
    assert not (tdir / "advisories.json").exists()
    assert not (tdir / "review").exists()


def test_read_and_display_use_new_file_and_legacy_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed(tmp_path, "KLC-S3")
    advisories.finish("KLC-S3", "build", [("t", [REC])], persist=True)
    assert advisories.read("KLC-S3", "build")["records"][0]["code"] == "t.c"
    assert advisories.for_display("KLC-S3", "build")["high"]
    assert advisories.read("KLC-S3", "design") is None
    # archived ticket: legacy per-phase file, read-only
    (tdir / "design").mkdir()
    (tdir / "design" / "ack-advisories.json").write_text(
        json.dumps({"records": [dict(REC, severity="medium")]}), encoding="utf-8")
    assert advisories.for_display("KLC-S3", "design")["medium"]


def test_auto_missing_key_clean_only_with_recorded_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-S4", history=["build:work", "build:ack-needed"])
    sig = gate_policy.collect_signals("KLC-S4", "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is True

    # no ack recorded for that phase: dirty
    sig = gate_policy.collect_signals("KLC-S4", "design")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is False

    # ack recorded but the file is unreadable: dirty (fail-closed)
    tdir = tmp_path / ".klc" / "tickets" / "KLC-S4"
    (tdir / "advisories.json").write_text("{not json", encoding="utf-8")
    sig = gate_policy.collect_signals("KLC-S4", "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is False
    (tdir / "advisories.json").write_text("[1]", encoding="utf-8")
    sig = gate_policy.collect_signals("KLC-S4", "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is False
