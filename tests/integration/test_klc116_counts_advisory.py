#!/usr/bin/env python3
"""KLC-116 step-5 — AC-14: observed/read/assumed counts per artefact, as a
warn-only advisory at the spec self-check and at the design ack. An artefact
that carries no attributed item reports nothing (not a stray `0/0/0`); a
frozen `_superseded/` snapshot never contributes to a count (D-202)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import provenance  # noqa: E402
import spec_selfcheck  # noqa: E402


def _seed(tmp_path: Path, ticket: str, files: dict[str, str]) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "tech", "phase": "build:work",
            "phase_history": [], "track": "M",
            "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 1, "total": 4},
            "affected_modules": ["core/skills"], "created": "2026-01-01T00:00:00Z"}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    for rel, body in files.items():
        p = tdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def test_spec_selfcheck_reports_evidence_counts_per_artifact():
    text = (
        "---\nticket: KLC-999\nauthority: agent\n---\n\n"
        "# spec\n\n## Goals\n\nx\n\n## Acceptance Criteria\n\n"
        "AC-1: a · b · c · d\n\n## Estimate\n\ntrack: M\n\n"
        "> [!FACT F-1] evidence=observed\n> claim\n\n"
        "> [!DECISION D-1] evidence=read src=a.py:1\n> claim\n"
    )
    rep = spec_selfcheck.self_check(text, "M")
    lines = spec_selfcheck.warn_lines(rep)
    assert any("observed=1" in l and "read=1" in l and "assumed=0" in l for l in lines)


def test_counts_advisory_omitted_when_artifact_has_no_attributed_items():
    text = (
        "---\nticket: KLC-999\nauthority: agent\n---\n\n"
        "# spec\n\n## Goals\n\nx\n\n## Acceptance Criteria\n\n"
        "AC-1: a · b · c · d\n\n## Estimate\n\ntrack: M\n"
    )
    rep = spec_selfcheck.self_check(text, "M")
    lines = spec_selfcheck.warn_lines(rep)
    assert not any("observed=" in l for l in lines)


def test_design_ack_reports_evidence_counts_per_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-970"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended: true)\n\n"
            "> [!DECISION D-1] evidence=observed\n"
            "> claim\n"
            "> ```\n> $ true\n> ok\n> ```\n"
        )
    })
    _block, warns = provenance.design_gate(ticket, "M")
    assert any("design/options.md" in w and "observed=1" in w for w in warns)


def test_counts_exclude_superseded_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-971"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended: true)\n\nprose\n"
        ),
        "_superseded/20260101T000000Z/design/options.md": (
            "> [!FACT F-1] evidence=observed\n"
            "> a frozen claim\n"
            "> ```\n> $ true\n> ok\n> ```\n"
        ),
    })
    _block, warns = provenance.design_gate(ticket, "M")
    assert not any("observed=" in w for w in warns)
