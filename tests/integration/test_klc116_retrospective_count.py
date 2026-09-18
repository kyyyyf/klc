#!/usr/bin/env python3
"""KLC-116 step-6 — AC-15: how many `assumed` items a later item contradicted,
computed over the scoped item index as the union of two edges it already
carries: a `supersedes=` back-link, and an explicit `refutes=` reference."""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import provenance  # noqa: E402


def _seed(tmp_path: Path, ticket: str, body: str) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    (tdir / "design").mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "tech", "phase": "build:work",
            "phase_history": [], "track": "M",
            "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 1, "total": 4},
            "affected_modules": ["core/skills"], "created": "2026-01-01T00:00:00Z"}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "design" / "options.md").write_text(body, encoding="utf-8")


def test_retrospective_counts_one_contradicted_assumed_item(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-980"
    _seed(tmp_path, ticket, (
        "> [!ASSUMPTION A-1] evidence=assumed if-false=revisit\n"
        "> the page scrolls\n\n"
        "> [!FACT F-1] evidence=observed refutes=A-1\n"
        "> the page does not scroll — measured with a real probe\n"
        "> ```\n> $ true\n> ok\n> ```\n\n"
        "> [!ASSUMPTION A-2] evidence=assumed if-false=revisit\n"
        "> an unrelated guess, never contradicted\n"
    ))
    rep = provenance.report(ticket)
    assert rep["contradicted_assumed"] == 1
    assert rep["contradicted_ids"] == ["A-1"]


def test_retrospective_reports_zero_when_no_contradiction(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-981"
    _seed(tmp_path, ticket, (
        "> [!ASSUMPTION A-1] evidence=assumed if-false=revisit\n"
        "> an assumption nothing ever contradicted\n"
    ))
    rep = provenance.report(ticket)
    assert rep["contradicted_assumed"] == 0
    assert rep["contradicted_ids"] == []
