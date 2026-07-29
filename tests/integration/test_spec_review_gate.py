#!/usr/bin/env python3
"""Integration: the KLC-084 independent spec reviewer wired into phase_completion.

A reviewer's `decisions_to_confirm[]` must reach the human at the discovery ack
(the existing `decision`-level gate) as an advisory line that leads with the
recommendation. Findings must be recorded for the build phase. When a review is
expected for the track but its output is absent, ack surfaces one degraded note
(never blocks). These acks still PASS — the reviewer elevates, it does not gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.phase_completion import can_complete_discovery  # noqa: E402

_M_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: human
risk_tags: []
---

## Goals
Ship the independent spec reviewer.

## Acceptance Criteria
- [ ] AC-1: the reviewer · emits · decisions_to_confirm · when a scope call is subjective

## Affected modules
- test_module: core/test.py

## Estimate
complexity: 2
uncertainty: 1
risk: 1
manual: 0
total: 4

- Option A: fast impl
- Option B: safer impl

Picked: Option A — lower risk
"""

_VERDICT = {
    "findings": [
        {"id": "F-1", "category": "untestable-ac", "severity": "medium",
         "ref": "AC-1", "detail": "condition names no observable outcome"}
    ],
    "decisions_to_confirm": [
        {"id": "D-1", "topic": "scope",
         "question": "flag prose style too?",
         "recommended": "no — only the five objective categories",
         "rationale": "keeps review low-noise"}
    ],
}


def _make_m_ticket(tmp_path: Path, ticket: str) -> Path:
    d = tmp_path / ".klc" / "tickets" / ticket
    d.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery:work",
        "track": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
        "affected_modules": ["test_module"], "layer": "code",
    }
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "spec.md").write_text(_M_SPEC.format(ticket=ticket), encoding="utf-8")
    return d


def test_decisions_reach_discovery_ack_with_recommendation(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _make_m_ticket(tmp_path, "KLC-R01")
    (d / "spec-review.md").write_text(
        "verdict\n\n```json\n" + json.dumps(_VERDICT) + "\n```\n", encoding="utf-8"
    )
    ok, msg = can_complete_discovery("KLC-R01")
    assert ok, f"reviewer elevates, does not gate; got: {msg!r}"
    assert "spec-review[decision D-1/scope]" in msg
    assert "RECOMMENDED:" in msg
    # HIGH-1(a): the OBJECTIVE findings are surfaced (collapsed count) at the ack.
    assert "finding(s) recorded" in msg
    # findings recorded for the build phase to assess.
    recorded = json.loads((d / "spec-review-findings.json").read_text())
    assert {f["id"] for f in recorded} == {"F-1"}


def test_probe_surfaces_but_does_not_write(tmp_path, monkeypatch):
    # codex P2: the read-only (persist=False) advisory probe surfaces the same
    # lines but must NOT write spec-review-findings.json.
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _make_m_ticket(tmp_path, "KLC-R03")
    (d / "spec-review.md").write_text(
        "verdict\n\n```json\n" + json.dumps(_VERDICT) + "\n```\n", encoding="utf-8"
    )
    ok, msg = can_complete_discovery("KLC-R03", persist=False)
    assert ok
    assert "RECOMMENDED:" in msg and "finding(s) recorded" in msg
    assert not (d / "spec-review-findings.json").exists()


def test_absent_review_on_M_surfaces_degraded_note_but_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_m_ticket(tmp_path, "KLC-R02")  # no spec-review.md
    ok, msg = can_complete_discovery("KLC-R02")
    assert ok
    assert "spec-review" in msg and "degraded" in msg
