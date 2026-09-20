#!/usr/bin/env python3
"""KLC-119 step-1 — AC-2/AC-3/AC-14 (D-207): `metrics.tokens.<phase>` becomes
an append-only attempts list, and `normalize_attempts` tolerates every shape
on disk without ever raising or silently discarding data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import budget_guard  # noqa: E402
import token_journal  # noqa: E402


def _seed(tmp_path: Path, ticket: str) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "build:work", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    mp = tdir / "meta.json"
    mp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return mp


def test_two_write_token_metrics_calls_same_ticket_and_phase_both_survive_with_distinct_ids(
        tmp_path, monkeypatch):
    """AC-2: two calls for the same (ticket, phase) leave two attempt
    records with distinct ids — a rework/retry pass is counted, not
    overwritten."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-A1")

    # KLC-119 step-2: write_token_metrics is transaction-aware — outside an
    # open scope it buffers into the journal instead (AC-4). This test is
    # about the attempts-list writer itself, so it simulates a transaction
    # being open, exactly as `state_tx`/`_drain_journal` do in production.
    with token_journal.scope("KLC-A1"):
        budget_guard.write_token_metrics("KLC-A1", "build", 100, 10, 0,
                                         source="estimated", card_bytes=400)
        budget_guard.write_token_metrics("KLC-A1", "build", 200, 20, 0,
                                         source="estimated", card_bytes=800)

    entry = json.loads(mp.read_text())["metrics"]["tokens"]["build"]
    attempts = entry["attempts"]
    assert len(attempts) == 2, f"expected 2 attempts, got {attempts}"
    ids = {a["id"] for a in attempts}
    assert len(ids) == 2, "the two attempts must carry distinct ids"
    assert attempts[0]["in"] == 100 and attempts[1]["in"] == 200


def test_estimated_attempt_never_rewrites_an_existing_provider_or_signal_attempt(
        tmp_path, monkeypatch):
    """AC-3: a later `estimated` write must not rewrite an existing
    `provider` or `signal` attempt in the list."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-A2")

    with token_journal.scope("KLC-A2"):
        budget_guard.write_token_metrics("KLC-A2", "review", 500, 100, 50,
                                         source="provider", card_bytes=1234)
        provider_attempt = json.loads(mp.read_text())[
            "metrics"]["tokens"]["review"]["attempts"][0]

        budget_guard.write_token_metrics("KLC-A2", "review", 10, 0, 0,
                                         source="estimated", card_bytes=999)
        budget_guard.write_token_metrics("KLC-A2", "review", 20, 0, 0,
                                         source="signal", card_bytes=1000)

    attempts = json.loads(mp.read_text())["metrics"]["tokens"]["review"]["attempts"]
    assert len(attempts) == 3
    # The original provider attempt is byte-identical, untouched.
    assert attempts[0] == provider_attempt
    sources = [a["source"] for a in attempts]
    assert sources == ["provider", "estimated", "signal"]


def test_normalize_attempts_degrades_a_non_dict_entry_with_a_warning_and_never_raises():
    """D-207/F-7: a `metrics.tokens.<phase>` value that is a bare list (or any
    non-record shape) degrades to zero attempts, the raw value preserved
    under `legacy`, and one warning — never an exception, never a silent
    discard."""
    result = budget_guard.normalize_attempts([{"in": 1}, {"in": 2}])
    assert result["attempts"] == []
    assert result["legacy"] == [{"in": 1}, {"in": 2}]
    assert len(result["warnings"]) == 1

    # Absent entirely.
    assert budget_guard.normalize_attempts(None) == {
        "attempts": [], "legacy": None, "warnings": []}
    assert budget_guard.normalize_attempts({}) == {
        "attempts": [], "legacy": None, "warnings": []}

    # A bare pre-KLC-119 record normalises to one legacy attempt.
    legacy_record = {"in": 5, "out": 1, "cache_hit": 0, "source": "provider"}
    out = budget_guard.normalize_attempts(legacy_record)
    assert len(out["attempts"]) == 1
    assert out["attempts"][0]["source"] == "provider"
    assert out["attempts"][0]["legacy"] is True
    assert out["legacy"] == legacy_record
    assert out["warnings"] == []

    # A string / number degrades the same way as a bare list.
    for garbage in ("not-a-record", 42, 3.14):
        out2 = budget_guard.normalize_attempts(garbage)
        assert out2["attempts"] == []
        assert out2["legacy"] == garbage
        assert len(out2["warnings"]) == 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
