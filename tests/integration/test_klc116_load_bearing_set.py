#!/usr/bin/env python3
"""KLC-116 step-3 — AC-11: the load-bearing set (the recommended option's
decision items, plus every id an impl-plan step names as a premise) derived
from structure alone, with the channel that put each id there."""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import provenance  # noqa: E402


def _seed(tmp_path: Path, ticket: str, files: dict[str, str]) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:work",
        "phase_history": [], "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 1, "total": 4},
        "affected_modules": ["core/skills"], "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    for rel, body in files.items():
        p = tdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tdir


def test_load_bearing_set_includes_recommended_option_decisions(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-930"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X\n\nnot recommended\n\n"
            "## Option B — do Y (recommended: true)\n\n"
            "> [!DECISION D-B] evidence=assumed if-false=y\n"
            "> the recommended decision\n"
        )
    })
    channels, notes = provenance.load_bearing(ticket)
    assert channels == {"D-B": "document"}
    assert notes == []


def test_non_recommended_option_decision_excluded(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-931"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X\n\n"
            "> [!DECISION D-A] evidence=assumed if-false=x\n"
            "> a decision made only inside the non-recommended option\n\n"
            "## Option B — do Y (recommended: true)\n\nrecommended\n"
        )
    })
    channels, notes = provenance.load_bearing(ticket)
    assert "D-A" not in channels


def test_load_bearing_set_includes_impl_plan_step_premises(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-932"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended: true)\n\n"
            "> [!ASSUMPTION A-1] evidence=assumed if-false=x\n"
            "> a premise a later build step depends on\n"
        ),
        "impl-plan.md": (
            "## step-1 — build the thing\n\n"
            "- Depends on: A-1\n"
        ),
    })
    channels, notes = provenance.load_bearing(ticket)
    assert channels["A-1"] == "step-premise"


def test_no_recommended_marker_degrades_and_excludes_option_sections(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-933"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X\n\n"
            "> [!DECISION D-A] evidence=assumed if-false=x\n"
            "> a decision with no marker anywhere in this document\n\n"
            "## Option B — do Y\n\nno marker here either\n"
        )
    })
    channels, notes = provenance.load_bearing(ticket)
    assert "D-A" not in channels
    assert any(n.dimension == "degraded" for n in notes)


def test_no_recommended_marker_accepts_bare_parenthetical_spelling(tmp_path, monkeypatch):
    """Both marker spellings accepted: `(recommended)` and `(recommended: true)`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-934"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended)\n\n"
            "> [!DECISION D-A] evidence=assumed if-false=x\n"
            "> a decision inside the recommended option\n"
        )
    })
    channels, notes = provenance.load_bearing(ticket)
    assert channels == {"D-A": "document"}
    assert notes == []


def test_document_level_decisions_are_load_bearing(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-935"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended: true)\n\nprose\n\n"
            "## Decisions\n\n"
            "> [!DECISION D-1] evidence=assumed if-false=x\n"
            "> a document-level decision, not nested under any option\n"
        )
    })
    channels, notes = provenance.load_bearing(ticket)
    assert channels == {"D-1": "document"}


def test_document_level_fact_is_load_bearing(tmp_path, monkeypatch):
    """review-fix (LOW, AC-11): D-302 broadened the document-channel filter
    from `type == "DECISION"` to `("DECISION", "ASSUMPTION", "FACT")` — a
    document-channel FACT item must land in the load-bearing set with
    channel `document`, mirroring the DECISION/ASSUMPTION rows above. No row
    exercised the FACT case before this fix."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-9351"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended: true)\n\nprose\n\n"
            "## Facts\n\n"
            "> [!FACT F-1] evidence=assumed if-false=x\n"
            "> a document-level fact, not nested under any option\n"
        )
    })
    channels, notes = provenance.load_bearing(ticket)
    assert channels == {"F-1": "document"}


def test_dangling_premise_id_is_surfaced_not_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-936"
    _seed(tmp_path, ticket, {
        "design/options.md": "## Option A — do X (recommended: true)\n\nprose\n",
        "impl-plan.md": (
            "## step-1 — build the thing\n\n"
            "- Depends on: TYPO-99\n"
        ),
    })
    channels, notes = provenance.load_bearing(ticket)
    assert "TYPO-99" not in channels
    assert any("TYPO-99" in n.message and "step-1" in n.message for n in notes)


def test_channel_is_step_premise_when_both_claim_the_same_id(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-937"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended: true)\n\n"
            "> [!DECISION D-1] evidence=assumed if-false=x\n"
            "> both a document-level decision and a step premise\n"
        ),
        "impl-plan.md": (
            "## step-1 — build the thing\n\n"
            "- Depends on: D-1\n"
        ),
    })
    channels, notes = provenance.load_bearing(ticket)
    assert channels["D-1"] == "step-premise"
