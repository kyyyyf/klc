#!/usr/bin/env python3
"""KLC-116 step-1 — AC-1/AC-2: `evidence` on the item header reaches the
ticket item index as a first-class key, and an out-of-vocabulary value is
named as a violation (mirroring how `dangling_refs` is reported).

Absence must read as absence: an item with no `evidence=` attribute gets no
synthesized/defaulted key in its index record (the fail-closed twin of AC-1).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import items  # noqa: E402


def _seed_ticket(tmp_path: Path, ticket: str, body: str) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    (tdir / "design").mkdir(parents=True)
    (tdir / "design" / "options.md").write_text(body, encoding="utf-8")
    return tdir


def test_evidence_reaches_item_index(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-900"
    _seed_ticket(tmp_path, ticket, (
        "> [!FACT F-1] evidence=observed\n"
        "> the button renders\n"
        "```\n$ true\nok\n```\n\n"
        "> [!ASSUMPTION A-1] evidence=assumed if-false=revisit\n"
        "> nobody will notice\n\n"
        "> [!DECISION D-1] evidence=read src=core/skills/items.py:1\n"
        "> use approach A\n"
    ))
    data = items.build_index(ticket, write=False)
    assert data["items"]["F-1"]["evidence"] == "observed"
    assert data["items"]["A-1"]["evidence"] == "assumed"
    assert data["items"]["D-1"]["evidence"] == "read"


def test_item_without_evidence_attribute_has_no_evidence_key_in_index(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-901"
    _seed_ticket(tmp_path, ticket, (
        "> [!FACT F-1] owner=ek\n"
        "> a claim with no evidence attribute at all\n"
    ))
    data = items.build_index(ticket, write=False)
    assert "evidence" not in data["items"]["F-1"]


def test_unknown_evidence_value_is_named_violation(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-902"
    _seed_ticket(tmp_path, ticket, (
        "> [!FACT F-1] evidence=inferred\n"
        "> a claim with a made-up vocabulary word\n"
    ))
    data = items.build_index(ticket, write=False)
    assert data["evidence_violations"] == [{"item": "F-1", "value": "inferred"}]


def test_three_known_values_produce_no_violation(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-903"
    _seed_ticket(tmp_path, ticket, (
        "> [!FACT F-1] evidence=observed\n"
        "> claim one\n\n"
        "> [!ASSUMPTION A-1] evidence=assumed if-false=x\n"
        "> claim two\n\n"
        "> [!DECISION D-1] evidence=read src=a.py:1\n"
        "> claim three\n"
    ))
    data = items.build_index(ticket, write=False)
    assert data["evidence_violations"] == []
