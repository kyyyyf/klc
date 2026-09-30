#!/usr/bin/env python3
"""KLC-119 step-1 — AC-1: `budget_guard.write_token_metrics` remains the ONE
writer of `meta.json:metrics.tokens`. A source-level scan over `core/` and
`klc-plugin/` must find no second writer, and the scan itself must actually
bite (negative twin) rather than vacuously pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import budget_guard  # noqa: E402


def test_write_token_metrics_is_the_only_writer_of_metrics_tokens():
    """AC-1: scanning the real source tree finds no second writer."""
    hits = budget_guard.find_second_writers(FW_ROOT)
    assert hits == [], (
        f"a second writer of metrics.tokens was found outside budget_guard.py: "
        f"{hits} — write_token_metrics must remain the single writer (AC-1)"
    )


def test_single_writer_check_fails_when_a_fixture_second_writer_is_introduced(
        tmp_path):
    """Negative twin: the grep must actually bite. Drop a fixture module that
    writes metrics.tokens directly into a scanned tmp tree and assert the
    check reports it."""
    fake_root = tmp_path / "fake_repo"
    fake_core = fake_root / "core" / "skills"
    fake_core.mkdir(parents=True)
    second_writer = fake_core / "sneaky_writer.py"
    second_writer.write_text(
        "def bad(meta, phase_id, rec):\n"
        "    tokens = meta.setdefault('metrics', {}).setdefault('tokens', {})\n"
        "    tokens[phase_id] = rec\n",
        encoding="utf-8",
    )
    hits = budget_guard.find_second_writers(fake_root)
    assert any(p.name == "sneaky_writer.py" for p in hits), (
        "the single-writer scan failed to catch a fixture second writer — "
        "the gate is vacuous"
    )


def test_find_second_writers_and_find_second_estimators_stay_empty_after_klc133():
    """AC-8: pin — after KLC-133 adds the six new attempt keys, both static
    scans still return an empty list; no second writer or second size-to-token
    rule was introduced anywhere in core/ or scripts/."""
    writer_hits = budget_guard.find_second_writers(FW_ROOT)
    assert writer_hits == [], f"a second writer of metrics.tokens was found: {writer_hits}"
    estimator_hits = budget_guard.find_second_estimators(FW_ROOT)
    assert estimator_hits == [], f"a second size-to-token rule was found: {estimator_hits}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
