#!/usr/bin/env python3
"""KLC-119 step-4 — AC-10/AC-11 (D-204): `klc metrics --rollup` aggregates
attempts with a three-way `source_counts`, plus `prompt_bytes_per_ticket`
and `review_passes_per_ticket` derived from measured data, never a literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import metrics  # noqa: E402


def _seed(tmp_path: Path, ticket: str, *, phase: str, track: str = "M",
          **extra) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
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


def test_rollup_reports_tokens_per_phase_per_track_with_source_counts_for_provider_signal_and_estimated(
        tmp_path, monkeypatch):
    """AC-10: `klc metrics --rollup` reports tokens per phase per track with
    `source_counts` split three ways over `provider`/`signal`/`estimated`,
    so an estimate is never presented as a measurement."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-200", phase="build:ack", track="M", metrics={
        "tokens": {
            "build": {"attempts": [
                {"id": "a1", "in": 100, "out": 10, "cache_hit": 5, "source": "provider"},
                {"id": "a2", "in": 20, "out": 2, "cache_hit": 0, "source": "signal"},
                {"id": "a3", "in": 30, "out": 3, "cache_hit": 0, "source": "estimated"},
            ]},
        },
    })

    payload = _rollup(tmp_path)
    bucket = payload["per_track"]["M"]["tokens_by_phase"]["build"]
    assert bucket["source_counts"] == {"provider": 1, "signal": 1, "estimated": 1}
    assert bucket["samples"] == 3


def test_rollup_reports_prompt_bytes_per_ticket_and_review_passes_per_ticket_against_expected_count(
        tmp_path, monkeypatch):
    """AC-11: the rollup reports `prompt_bytes_per_ticket` and
    `review_passes_per_ticket` (actual over a measured expected count),
    never a bare literal."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed(tmp_path, "KLC-100", phase="build:ack", track="M", metrics={
        "tokens": {
            "discovery": {"attempts": [
                {"id": "b1", "in": 500, "out": 0, "cache_hit": 0,
                 "source": "estimated", "card_bytes": 2000},
            ]},
        },
    })
    for name in ("spec-review.md", "test-plan-review.md",
                "impl-plan-review.md", "review-report.md"):
        (tdir / name).write_text("ok\n", encoding="utf-8")

    payload = _rollup(tmp_path)
    m_track = payload["per_track"]["M"]
    assert m_track["prompt_bytes_per_ticket"] == 2000
    rpt = m_track["review_passes_per_ticket"]
    assert rpt["expected"] == 4  # KLC-100 is in the KLC-096..102 era (F-018)
    assert rpt["actual"] == 4
    assert rpt["ratio"] == 1.0


def test_degraded_review_does_not_lower_the_review_passes_ratio_denominator(
        tmp_path, monkeypatch):
    """AC-11: a degraded review only ever lowers the numerator of
    `review_passes_per_ticket`, never the expected denominator (Q-004)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed(tmp_path, "KLC-110", phase="build:ack", track="M")
    # Only 2 of the 6 expected artefacts for a KLC-103+ M ticket are present
    # (a degraded spec-review/test-plan-review, matching F-R8/F-019's real
    # precedent) — the DENOMINATOR must not shrink because of it.
    for name in ("impl-plan-review.md", "review-report.md"):
        (tdir / name).write_text("ok\n", encoding="utf-8")

    payload = _rollup(tmp_path)
    rpt = payload["per_track"]["M"]["review_passes_per_ticket"]
    assert rpt["expected"] == 6, \
        "a degraded review must not lower the denominator (Q-004)"
    assert rpt["actual"] == 2
    assert rpt["ratio"] == 2 / 6


def test_expected_review_artefacts_scores_both_historical_review_eras_correctly(
        tmp_path, monkeypatch):
    """Design-time correction F-4/D-204: an M ticket in the KLC-096..102 era
    scores 4 of 4, and one in the KLC-103..118 era scores 4 of 6 (F-018's
    two observed shapes, F-019's "six designed")."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    early_dir = _seed(tmp_path, "KLC-098", phase="learn:ack", track="M")
    for name in ("spec-review.md", "test-plan-review.md",
                "impl-plan-review.md", "review-report.md"):
        (early_dir / name).write_text("ok\n", encoding="utf-8")
    early_meta = json.loads((early_dir / "meta.json").read_text())
    assert metrics.expected_review_artefacts("M", "KLC-098", early_meta) == 4
    assert metrics.actual_review_artefacts("M", "KLC-098", early_meta, early_dir) == 4

    later_dir = _seed(tmp_path, "KLC-112", phase="learn:ack", track="M")
    for name in ("spec-review.md", "test-plan-review.md",
                "impl-plan-review.md", "review-report.md"):
        (later_dir / name).write_text("ok\n", encoding="utf-8")
    later_meta = json.loads((later_dir / "meta.json").read_text())
    assert metrics.expected_review_artefacts("M", "KLC-112", later_meta) == 6
    assert metrics.actual_review_artefacts("M", "KLC-112", later_meta, later_dir) == 4


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
