#!/usr/bin/env python3
"""KLC-120 step-1 — AC-4: `klc metrics --rollup` reports a per-track
`review_llm_passes_per_ticket` figure counted from reviewer-tagged attempt
records, `None` when no ticket of the track carries one (D-013)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import metrics  # noqa: E402


def _seed(tmp_path: Path, ticket: str, *, track: str = "M", **extra) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "build:ack", "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    meta.update(extra)
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    return tdir


def _rollup(tmp_path: Path) -> dict:
    metrics.cmd_rollup(None)
    out = tmp_path / ".klc" / "knowledge" / "process-metrics.json"
    return json.loads(out.read_text(encoding="utf-8"))


def test_rollup_reports_review_llm_passes_per_ticket_from_tagged_attempts(
        tmp_path, monkeypatch):
    """AC-4: the rollup counts reviewer-tagged attempts per ticket and
    averages them over the tickets that carry at least one (D-013) — an
    untagged attempt (e.g. a non-review phase) is never counted."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-300", track="M", metrics={
        "tokens": {"review": {"attempts": [
            {"id": "r1", "in": 10, "out": 1, "cache_hit": 0,
             "source": "estimated", "reviewer": "code-review"},
            {"id": "r2", "in": 10, "out": 1, "cache_hit": 0,
             "source": "estimated", "reviewer": "drift"},
        ]}},
    })
    _seed(tmp_path, "KLC-301", track="M", metrics={
        "tokens": {"review": {"attempts": [
            {"id": "r3", "in": 10, "out": 1, "cache_hit": 0,
             "source": "estimated", "reviewer": "external"},
            {"id": "r4", "in": 10, "out": 1, "cache_hit": 0,
             "source": "estimated", "reviewer": "code-review"},
            {"id": "r5", "in": 10, "out": 1, "cache_hit": 0,
             "source": "estimated", "reviewer": "drift"},
            {"id": "r6", "in": 10, "out": 1, "cache_hit": 0,
             "source": "estimated"},   # untagged — must not be counted
        ]}},
    })

    payload = _rollup(tmp_path)
    m_track = payload["per_track"]["M"]
    assert m_track["review_llm_passes_per_ticket"] == 2.5   # (2 + 3) / 2
    assert m_track["review_llm_passes_measured_tickets"] == 2


def test_rollup_review_llm_passes_per_ticket_is_none_when_no_tagged_attempts(
        tmp_path, monkeypatch):
    """Fail-closed twin: a track with zero reviewer-tagged attempts reads
    `None`, never `0` — 'not measured' must never read as 'costs nothing'."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-302", track="S", metrics={
        "tokens": {"review": {"attempts": [
            {"id": "s1", "in": 10, "out": 1, "cache_hit": 0,
             "source": "estimated"},   # untagged
        ]}},
    })

    payload = _rollup(tmp_path)
    s_track = payload["per_track"]["S"]
    assert s_track["review_llm_passes_per_ticket"] is None
    assert s_track["review_llm_passes_measured_tickets"] == 0


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
