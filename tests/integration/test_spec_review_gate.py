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
from core.skills import advisories as _adv  # noqa: E402  (KLC-117)

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
    # KLC-117: the ack's return value is now the aggregator's one-line summary;
    # the routed decision / findings content lives in the persisted artifact.
    assert msg  # non-empty: a high (decision) + a medium (findings) were collected
    envelope = _adv.read("KLC-R01", "discovery")
    assert envelope is not None
    messages = [r["message"] for r in envelope["records"]]
    assert any("spec-review[decision D-1/scope]" in m for m in messages)
    assert any("RECOMMENDED:" in m for m in messages)
    # HIGH-1(a): the OBJECTIVE findings are surfaced (collapsed count) at the ack.
    assert any("finding(s) recorded" in m for m in messages)
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
    # KLC-117: persist=False writes NOTHING (C-002) — not spec-review-findings.json
    # and not ack-advisories.json — but the probe still computes the SAME summary
    # a persisting call would (test_klc117_aggregator_single_path.py pins this).
    assert msg  # non-empty: the same records as the persisting path, just unwritten
    assert not (d / "spec-review-findings.json").exists()
    assert _adv.read("KLC-R03", "discovery") is None


def test_absent_review_on_M_surfaces_degraded_note_but_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_m_ticket(tmp_path, "KLC-R02")  # no spec-review.md
    ok, msg = can_complete_discovery("KLC-R02")
    assert ok
    assert msg  # non-empty: at least the degraded note was collected
    envelope = _adv.read("KLC-R02", "discovery")
    assert envelope is not None
    assert any("spec-review" in r["message"] and "degraded" in r["message"]
              for r in envelope["records"])
