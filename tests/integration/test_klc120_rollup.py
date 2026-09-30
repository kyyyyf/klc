#!/usr/bin/env python3
"""KLC-120 step-1 — AC-4: `klc metrics --rollup` reports a per-track
`review_llm_passes_per_ticket` figure counted from reviewer-tagged attempt
records, `None` when no ticket of the track carries one (D-013)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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


# --- KLC-127 step-8 (AC-18): review_duplicate_rate ---------------------------

def _write_pool(tdir: Path, duplicate_rate, *, raw_count: int = 4) -> None:
    pool = {"ticket": tdir.name, "min_similarity": 0.15, "raw_count": raw_count,
            "pooled_count": 2, "duplicate_rate": duplicate_rate, "findings": []}
    path = tdir / "review" / "findings-pool.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pool, indent=2) + "\n", encoding="utf-8")


def test_rollup_reports_per_track_review_duplicate_rate_averaged_over_tickets_with_a_pool(
        tmp_path, monkeypatch):
    """AC-18: the per-track review_duplicate_rate averages only the tickets
    that carry a findings-pool.json; a ticket with none is not counted."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    t1 = _seed(tmp_path, "KLC-400", track="L")
    t2 = _seed(tmp_path, "KLC-401", track="L")
    _seed(tmp_path, "KLC-402", track="L")  # no pool at all
    _write_pool(t1, 0.5)
    _write_pool(t2, 0.3)

    payload = _rollup(tmp_path)
    l_track = payload["per_track"]["L"]
    assert l_track["review_duplicate_rate"] == pytest.approx(0.4)


def test_rollup_review_duplicate_rate_is_none_for_a_track_with_no_pooled_ticket(
        tmp_path, monkeypatch):
    """AC-18: 'not measured' must never read as 'costs nothing' — a track
    whose tickets carry no pool at all reads None, never 0."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-403", track="XS")

    payload = _rollup(tmp_path)
    xs_track = payload["per_track"]["XS"]
    assert xs_track["review_duplicate_rate"] is None


def test_rollup_ignores_a_pool_whose_duplicate_rate_is_null(tmp_path, monkeypatch):
    """AC-18/AC-17: a pool with a null duplicate_rate (raw_count 0) is not
    averaged in — mixing None into a numeric mean must not happen."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    t1 = _seed(tmp_path, "KLC-404", track="M")
    t2 = _seed(tmp_path, "KLC-405", track="M")
    _write_pool(t1, 0.6)
    _write_pool(t2, None)

    payload = _rollup(tmp_path)
    m_track = payload["per_track"]["M"]
    assert m_track["review_duplicate_rate"] == pytest.approx(0.6)


def test_every_existing_rollup_figure_is_unchanged_when_pools_are_added(
        tmp_path, monkeypatch):
    """AC-18: adding findings-pool.json files changes only the new
    review_duplicate_rate key — every other per-track figure for the same
    corpus stays byte/value-identical."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-406", track="M", metrics={
        "tokens": {"review": {"attempts": [
            {"id": "r1", "in": 10, "out": 1, "cache_hit": 0,
             "source": "estimated", "reviewer": "code-review"},
        ]}},
    })
    t2 = _seed(tmp_path, "KLC-407", track="M")

    before = _rollup(tmp_path)["per_track"]["M"]
    _write_pool(t2, 0.25)
    after = _rollup(tmp_path)["per_track"]["M"]

    before_no_rate = {k: v for k, v in before.items() if k != "review_duplicate_rate"}
    after_no_rate = {k: v for k, v in after.items() if k != "review_duplicate_rate"}
    assert before_no_rate == after_no_rate
    assert before["review_duplicate_rate"] is None
    assert after["review_duplicate_rate"] == pytest.approx(0.25)


# --- KLC-127 step-12 (F-3): review_duplicate_rate is weighted by raw_count --

def test_rollup_weights_review_duplicate_rate_by_raw_count(tmp_path, monkeypatch):
    """F-3: a 2-finding ticket must not count as much as an 18-finding one —
    the per-track mean is weighted by each ticket's raw_count, not a plain
    per-ticket average. Unweighted would give (0.5+0.9)/2=0.7; weighted by
    raw_count (2 and 18) gives (0.5*2 + 0.9*18)/20 = 0.86."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    t1 = _seed(tmp_path, "KLC-410", track="L")
    t2 = _seed(tmp_path, "KLC-411", track="L")
    _write_pool(t1, 0.5, raw_count=2)
    _write_pool(t2, 0.9, raw_count=18)

    payload = _rollup(tmp_path)
    l_track = payload["per_track"]["L"]
    assert l_track["review_duplicate_rate"] == pytest.approx(0.86)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
