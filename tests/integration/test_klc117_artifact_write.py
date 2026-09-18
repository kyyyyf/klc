#!/usr/bin/env python3
"""KLC-117 step-3 — AC-4/AC-5: the gate writes the artifact on the persisting
path and writes nothing on a probe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402


def _ticket_dir(tmp_path: Path, ticket: str) -> Path:
    d = tmp_path / ".klc" / "tickets" / ticket
    d.mkdir(parents=True)
    return d


def test_persisting_ack_writes_ack_advisories_json(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket_dir(tmp_path, "KLC-A1")

    sources = [("test-producer", [{"source": "test-producer", "severity": "high",
                                   "code": "t.c", "message": "m", "ref": ""}])]
    records, summary = advisories.finish("KLC-A1", "discovery", sources, persist=True)

    path = tmp_path / ".klc" / "tickets" / "KLC-A1" / "discovery" / "ack-advisories.json"
    assert path.exists()
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == advisories.SCHEMA_VERSION
    assert envelope["ticket"] == "KLC-A1"
    assert envelope["phase"] == "discovery"
    assert "generated_at" in envelope
    assert envelope["records"] == records
    assert summary  # non-empty since there is a high record


def test_probe_persist_false_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket_dir(tmp_path, "KLC-A2")

    def _boom(*a, **k):
        raise AssertionError("must not write on a read-only probe")

    monkeypatch.setattr(Path, "write_text", _boom, raising=True)
    sources = [("test-producer", [{"source": "test-producer", "severity": "high",
                                   "code": "t.c", "message": "m", "ref": ""}])]
    records, summary = advisories.finish("KLC-A2", "discovery", sources, persist=False)

    path = tmp_path / ".klc" / "tickets" / "KLC-A2" / "discovery" / "ack-advisories.json"
    assert not path.exists()
    assert records  # the decision/summary is unaffected by persistence
    assert summary


def test_unwritable_artifact_path_degrades_without_raising(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket_dir(tmp_path, "KLC-A3")

    def _boom_mkdir(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "mkdir", _boom_mkdir, raising=True)
    sources = [("test-producer", [{"source": "test-producer", "severity": "high",
                                   "code": "t.c", "message": "m", "ref": ""}])]
    records, summary = advisories.finish("KLC-A3", "discovery", sources, persist=True)
    assert records  # never raises; degrades instead
    assert summary
