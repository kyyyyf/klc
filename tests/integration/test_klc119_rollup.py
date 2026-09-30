#!/usr/bin/env python3
"""KLC-119 step-4 — AC-10/AC-11 (D-204): `klc metrics --rollup` aggregates
attempts with a three-way `source_counts`, plus `prompt_bytes_per_ticket`
and `review_passes_per_ticket` derived from measured data, never a literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# KLC-133 AC-10/AC-11: by_source buckets and measured_per_ticket
# ---------------------------------------------------------------------------

def test_rollup_reports_by_source_with_provider_signal_estimated_buckets(
        tmp_path, monkeypatch):
    """AC-10: each phase entry has a `by_source` object keyed by
    provider/signal/estimated, each with its own samples/avg_in/avg_out/
    avg_cache_hit, and `provider` additionally with avg_cache_write/
    avg_num_turns/cost_usd_total/failed_samples."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-300", phase="build:ack", track="M", metrics={
        "tokens": {
            "build": {"attempts": [
                {"id": "a1", "in": 100, "out": 10, "cache_hit": 5,
                 "cache_write": 20, "cost_usd": 0.1, "num_turns": 2,
                 "source": "provider"},
                {"id": "a2", "in": 20, "out": 2, "cache_hit": 0, "source": "signal"},
                {"id": "a3", "in": 30, "out": 3, "cache_hit": 0,
                 "source": "estimated", "card_bytes": 120},
                {"id": "a4", "in": 999, "out": 999, "cache_hit": 999,
                 "cost_usd": 0.2, "failed": True, "source": "provider"},
            ]},
        },
    })

    payload = _rollup(tmp_path)
    by_source = payload["per_track"]["M"]["tokens_by_phase"]["build"]["by_source"]
    assert set(by_source) == {"provider", "signal", "estimated"}
    for source in ("provider", "signal", "estimated"):
        bucket = by_source[source]
        assert "samples" in bucket and "avg_in" in bucket
        assert "avg_out" in bucket and "avg_cache_hit" in bucket
    provider = by_source["provider"]
    assert "avg_cache_write" in provider
    assert "avg_num_turns" in provider
    assert "cost_usd_total" in provider
    assert "failed_samples" in provider


def test_failed_attempt_counts_in_samples_and_cost_but_not_in_averages(
        tmp_path, monkeypatch):
    """AC-10/Q-004: a failed provider attempt counts in samples,
    failed_samples and cost_usd_total, but its in/out/cache_hit/
    cache_write/num_turns are excluded from the averages."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-301", phase="build:ack", track="M", metrics={
        "tokens": {
            "build": {"attempts": [
                {"id": "a1", "in": 100, "out": 10, "cache_hit": 0,
                 "cache_write": 0, "cost_usd": 0.1, "num_turns": 1,
                 "source": "provider"},
                {"id": "a2", "in": 100000, "out": 100000, "cache_hit": 100000,
                 "cache_write": 100000, "cost_usd": 5.0, "num_turns": 100,
                 "failed": True, "source": "provider"},
            ]},
        },
    })

    payload = _rollup(tmp_path)
    provider = payload["per_track"]["M"]["tokens_by_phase"]["build"]["by_source"]["provider"]
    assert provider["samples"] == 2
    assert provider["failed_samples"] == 1
    assert provider["cost_usd_total"] == pytest.approx(5.1)
    assert provider["avg_in"] == 100
    assert provider["avg_out"] == 10
    assert provider["avg_num_turns"] == 1
    assert provider["avg_cache_write"] == 0


def test_no_phase_figure_is_averaged_over_more_than_one_source(tmp_path, monkeypatch):
    """AC-10: no top-level avg_in/avg_out/avg_cache_hit is left mixing
    sources in the phase entry — every averaged figure lives under exactly
    one `by_source` bucket."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-302", phase="build:ack", track="M", metrics={
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
    assert "avg_in" not in bucket
    assert "avg_out" not in bucket
    assert "avg_cache_hit" not in bucket
    assert "samples" in bucket
    assert "source_counts" in bucket


def test_prompt_bytes_per_ticket_sums_card_bytes_of_estimated_attempts_only(
        tmp_path, monkeypatch):
    """AC-10/F-016: prompt_bytes_per_ticket sums the card_bytes of
    estimated attempts only — a provider attempt is never double-counted
    into the prompt-size figure even if it happens to carry card_bytes."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-303", phase="build:ack", track="M", metrics={
        "tokens": {
            "build": {"attempts": [
                {"id": "a1", "in": 100, "out": 10, "cache_hit": 0,
                 "card_bytes": 9999, "source": "provider"},
                {"id": "a2", "in": 30, "out": 3, "cache_hit": 0,
                 "card_bytes": 400, "source": "estimated"},
            ]},
        },
    })

    payload = _rollup(tmp_path)
    assert payload["per_track"]["M"]["prompt_bytes_per_ticket"] == 400


def test_empty_source_bucket_reports_zero_samples_and_null_averages(
        tmp_path, monkeypatch):
    """AC-10: a source with zero attempts in a phase still gets its own
    bucket, with samples 0 and every average null."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-304", phase="build:ack", track="M", metrics={
        "tokens": {
            "build": {"attempts": [
                {"id": "a1", "in": 100, "out": 10, "cache_hit": 0, "source": "estimated"},
            ]},
        },
    })

    payload = _rollup(tmp_path)
    by_source = payload["per_track"]["M"]["tokens_by_phase"]["build"]["by_source"]
    for source in ("provider", "signal"):
        bucket = by_source[source]
        assert bucket["samples"] == 0
        assert bucket["avg_in"] is None
        assert bucket["avg_out"] is None
        assert bucket["avg_cache_hit"] is None
    assert by_source["provider"]["cost_usd_total"] is None
    assert by_source["provider"]["failed_samples"] == 0


def test_attempts_without_the_new_keys_read_as_not_reported(tmp_path, monkeypatch):
    """AC-10: a pre-KLC-133 provider attempt (no cost_usd/cache_write/
    num_turns at all) reads its by_source figures as null, never 0."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-305", phase="build:ack", track="M", metrics={
        "tokens": {
            "build": {"attempts": [
                {"id": "a1", "in": 100, "out": 10, "cache_hit": 5, "source": "provider"},
            ]},
        },
    })

    payload = _rollup(tmp_path)
    provider = payload["per_track"]["M"]["tokens_by_phase"]["build"]["by_source"]["provider"]
    assert provider["cost_usd_total"] is None
    assert provider["avg_cache_write"] is None
    assert provider["avg_num_turns"] is None


def test_rollup_skips_non_numeric_attempt_values_without_raising(tmp_path, monkeypatch):
    """AC-10: a hand-edited corpus with a string `in`, a bool `num_turns`,
    a string `cost_usd` and an unknown source never raises — those values
    are simply skipped."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-306", phase="build:ack", track="M", metrics={
        "tokens": {
            "build": {"attempts": [
                {"id": "a1", "in": "not-a-number", "out": 10, "cache_hit": 0,
                 "num_turns": True, "cost_usd": "free", "source": "provider"},
                {"id": "a2", "in": 5, "out": 1, "cache_hit": 0, "source": "mystery"},
            ]},
        },
    })

    payload = _rollup(tmp_path)  # must not raise
    provider = payload["per_track"]["M"]["tokens_by_phase"]["build"]["by_source"]["provider"]
    assert provider["avg_in"] is None
    assert provider["avg_num_turns"] is None
    assert provider["cost_usd_total"] is None


def test_measured_per_ticket_averages_over_fully_measured_tickets_only(
        tmp_path, monkeypatch):
    """AC-11 (test-plan-review F-2): measured_per_ticket.review and .build
    each independently report tickets==2 (fully measured), partial_tickets==1
    (mixed provider/estimated tagged attempts), averaged only over the two
    fully-measured tickets; a ticket fully-measured on one phase and
    estimated-only on the other counts correctly in each bucket
    independently."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    _seed(tmp_path, "KLC-M1", phase="build:ack", track="M", metrics={"tokens": {
        "review": {"attempts": [
            {"id": "r1", "in": 10, "out": 5, "cache_hit": 0, "cost_usd": 0.1,
             "num_turns": 1, "reviewer": "security", "source": "provider"},
        ]},
        "build": {"attempts": [
            {"id": "b1", "in": 100, "out": 50, "cache_hit": 0, "cost_usd": 1.0,
             "num_turns": 2, "run_pass": "step", "source": "provider"},
        ]},
    }})
    _seed(tmp_path, "KLC-M2", phase="build:ack", track="M", metrics={"tokens": {
        "review": {"attempts": [
            {"id": "r2", "in": 20, "out": 10, "cache_hit": 0, "cost_usd": 0.2,
             "num_turns": 3, "reviewer": "architecture", "source": "provider"},
        ]},
        "build": {"attempts": [
            {"id": "b2", "in": 200, "out": 100, "cache_hit": 0, "cost_usd": 2.0,
             "num_turns": 4, "run_pass": "step", "source": "provider"},
        ]},
    }})
    _seed(tmp_path, "KLC-M3", phase="build:ack", track="M", metrics={"tokens": {
        "review": {"attempts": [
            {"id": "r3a", "in": 999, "out": 999, "cache_hit": 0, "cost_usd": 9,
             "num_turns": 9, "reviewer": "performance", "source": "provider"},
            {"id": "r3b", "in": 30, "out": 3, "cache_hit": 0, "card_bytes": 30,
             "reviewer": "performance", "source": "estimated"},
        ]},
        "build": {"attempts": [
            {"id": "b3a", "in": 999, "out": 999, "cache_hit": 0, "cost_usd": 9,
             "num_turns": 9, "run_pass": "step", "source": "provider"},
            {"id": "b3b", "in": 40, "out": 4, "cache_hit": 0, "card_bytes": 40,
             "run_pass": "step", "source": "estimated"},
        ]},
    }})
    _seed(tmp_path, "KLC-M4", phase="build:ack", track="M", metrics={"tokens": {
        "review": {"attempts": [
            {"id": "r4", "in": 5, "out": 1, "cache_hit": 0, "card_bytes": 5,
             "reviewer": "security", "source": "estimated"},
        ]},
        "build": {"attempts": [
            {"id": "b4", "in": 6, "out": 1, "cache_hit": 0, "card_bytes": 6,
             "run_pass": "step", "source": "estimated"},
        ]},
    }})

    payload = _rollup(tmp_path)
    m = payload["per_track"]["M"]["measured_per_ticket"]

    assert m["review"]["tickets"] == 2
    assert m["review"]["partial_tickets"] == 1
    assert m["review"]["avg_total_input"] == pytest.approx(15)
    assert m["review"]["avg_out"] == pytest.approx(7.5)
    assert m["review"]["avg_cost_usd"] == pytest.approx(0.15)
    assert m["review"]["avg_num_turns"] == pytest.approx(2)

    assert m["build"]["tickets"] == 2
    assert m["build"]["partial_tickets"] == 1
    assert m["build"]["avg_total_input"] == pytest.approx(150)
    assert m["build"]["avg_out"] == pytest.approx(75)
    assert m["build"]["avg_cost_usd"] == pytest.approx(1.5)
    assert m["build"]["avg_num_turns"] == pytest.approx(3)


def test_measured_per_ticket_figures_are_null_not_zero_when_no_ticket_qualifies(
        tmp_path, monkeypatch):
    """AC-11: with zero fully-measured tickets, every measured_per_ticket
    figure is JSON null, never 0."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-N1", phase="build:ack", track="M", metrics={"tokens": {
        "review": {"attempts": [
            {"id": "n1", "in": 5, "out": 1, "cache_hit": 0, "card_bytes": 5,
             "reviewer": "security", "source": "estimated"},
        ]},
    }})

    payload = _rollup(tmp_path)
    m = payload["per_track"]["M"]["measured_per_ticket"]
    assert m["review"]["tickets"] == 0
    assert m["review"]["partial_tickets"] == 0
    for key in ("avg_total_input", "avg_out", "avg_cost_usd", "avg_num_turns"):
        assert m["review"][key] is None
    assert m["build"]["tickets"] == 0
    for key in ("avg_total_input", "avg_out", "avg_cost_usd", "avg_num_turns"):
        assert m["build"][key] is None


def test_ticket_whose_tagged_provider_attempts_all_failed_counts_in_neither(
        tmp_path, monkeypatch):
    """AC-11/impl-plan-review F-8: a ticket whose tagged provider attempts
    ALL failed counts in NEITHER tickets nor partial_tickets, but its cost
    still counts in by_source.provider.cost_usd_total."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-F1", phase="build:ack", track="M", metrics={"tokens": {
        "review": {"attempts": [
            {"id": "f1", "in": 10, "out": 5, "cache_hit": 0, "cost_usd": 0.5,
             "failed": True, "reviewer": "security", "source": "provider"},
        ]},
    }})

    payload = _rollup(tmp_path)
    m = payload["per_track"]["M"]["measured_per_ticket"]
    assert m["review"]["tickets"] == 0
    assert m["review"]["partial_tickets"] == 0
    provider = payload["per_track"]["M"]["tokens_by_phase"]["review"]["by_source"]["provider"]
    assert provider["cost_usd_total"] == pytest.approx(0.5)


def test_review_llm_passes_per_ticket_counts_only_non_failed_reviewer_tagged_review_attempts(
        tmp_path, monkeypatch):
    """AC-11: review_llm_passes_per_ticket counts only non-failed
    reviewer-tagged attempts of phase review — a failed one is excluded
    (correcting F-015), and a build-phase attempt (never reviewer-tagged)
    never contributes either."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-C1", phase="build:ack", track="M", metrics={"tokens": {
        "review": {"attempts": [
            {"id": "c1", "in": 10, "out": 5, "cache_hit": 0,
             "reviewer": "security", "source": "provider"},
            {"id": "c2", "in": 10, "out": 5, "cache_hit": 0, "failed": True,
             "reviewer": "architecture", "source": "provider"},
        ]},
        "build": {"attempts": [
            {"id": "c3", "in": 10, "out": 5, "cache_hit": 0,
             "run_pass": "step", "source": "provider"},
        ]},
    }})

    payload = _rollup(tmp_path)
    assert payload["per_track"]["M"]["review_llm_passes_per_ticket"] == 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
