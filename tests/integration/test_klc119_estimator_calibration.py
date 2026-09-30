#!/usr/bin/env python3
"""KLC-119 step-4 — AC-8: the estimator's calibration status is derived from
the corpus, never a hardcoded claim.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import budget_guard  # noqa: E402


def test_calibration_statement_declares_uncalibrated_when_no_provider_records_exist_in_corpus():
    """AC-8: with zero `provider`-sourced attempts anywhere, the estimator's
    derived calibration statement must read "uncalibrated", never a
    hardcoded claim of accuracy."""
    by_phase = {
        "build": [{"source": "estimated", "in": 100}],
        "review": [{"source": "estimated", "in": 50}],
    }
    assert budget_guard.calibration_statement(by_phase) == \
        "uncalibrated: no provider-sourced attempts in the corpus"
    assert budget_guard.calibration_statement({}) == \
        "uncalibrated: no provider-sourced attempts in the corpus"


def test_calibration_statement_computes_estimated_to_actual_ratio_from_provider_sourced_attempts_when_present():
    """AC-8: the calibration statement is derived from the corpus — when
    `provider`-sourced attempts exist, it reports the computed
    estimated-to-actual ratio rather than "uncalibrated"."""
    by_phase = {
        "build": [
            {"source": "provider", "in": 1000},
            {"source": "estimated", "in": 1100},
        ],
        "review": [
            {"source": "provider", "in": 500},
            {"source": "estimated", "in": 400},
        ],
        # a phase with no provider attempt contributes no pair.
        "design": [{"source": "estimated", "in": 300}],
    }
    statement = budget_guard.calibration_statement(by_phase)
    # (1100/1000 + 400/500) / 2 = (1.10 + 0.80) / 2 = 0.95 (D-110: the ratio
    # is unchanged — neither attempt here carries cache_hit/cache_write, so
    # the new "provider total input" equals the old bare "in").
    assert statement == (
        "estimated in / provider total input (in + cache_hit + cache_write) = "
        "0.95 over 2 provider-paired phases")


def test_estimator_calibration_compares_estimated_in_with_provider_total_input():
    """AC-11: fixes F-012 — the calibration compares an estimated attempt's
    `in` (the whole card) against a provider attempt's TOTAL input
    (in + cache_hit + cache_write), not its uncached `in` alone."""
    by_phase = {
        "build": [
            {"source": "provider", "in": 100, "cache_hit": 700, "cache_write": 200},
            {"source": "estimated", "in": 1000},
        ],
    }
    statement = budget_guard.calibration_statement(by_phase)
    # provider total input = 100 + 700 + 200 = 1000; estimated in = 1000.
    assert statement == (
        "estimated in / provider total input (in + cache_hit + cache_write) = "
        "1.00 over 1 provider-paired phases")


def test_calibration_skips_failed_provider_attempts():
    """AC-11: a failed provider attempt is skipped — only the LAST
    non-failed provider attempt of a phase is paired with the estimate."""
    by_phase = {
        "build": [
            {"source": "provider", "in": 100, "failed": True},
            {"source": "provider", "in": 900},
            {"source": "estimated", "in": 900},
        ],
    }
    statement = budget_guard.calibration_statement(by_phase)
    assert statement == (
        "estimated in / provider total input (in + cache_hit + cache_write) = "
        "1.00 over 1 provider-paired phases")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
