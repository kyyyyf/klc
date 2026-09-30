#!/usr/bin/env python3
"""tests/test_budget_guard.py — KLC-052 step-2: budget_guard extraction.

check_prompt_budget(track, estimated) is the advisory (non-dispatching)
counterpart of runner.py's inline hard/soft-limit guard, so the
orchestrator can decide whether to even attempt a dispatch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import budget_guard  # noqa: E402
import token_journal  # noqa: E402


def test_hard_breach_is_flagged():
    with patch.object(budget_guard, "load_budget_limits",
                       return_value=({"XS": 100}, {"XS": 200})):
        verdict = budget_guard.check_prompt_budget("XS", 250)
    assert verdict.hard_breach is True
    print("PASS: hard breach is flagged")


def test_soft_breach_warns_not_blocks():
    with patch.object(budget_guard, "load_budget_limits",
                       return_value=({"XS": 100}, {"XS": 200})):
        verdict = budget_guard.check_prompt_budget("XS", 150)
    assert verdict.hard_breach is False
    assert verdict.soft_breach is True
    print("PASS: soft breach warns, does not block")


# --- KLC-133 AC-8: the six new attempt keys -----------------------------------

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


# D-112: these two literals are `budget_guard.attempt_record`'s OWN output
# for these exact inputs, captured via `git show main:core/skills/budget_guard.py`
# on 2026-09-30 (before this ticket touched the module) — a caller passing none
# of the six new keys must write a byte-identical record after KLC-133.
_BASELINE_PROVIDER = dict(
    kwargs=dict(tokens_in=500, tokens_out=100, cache_hit=50, source="provider",
                card_bytes=1234, step=3, attempt_id="deadbeef0001",
                ts="2026-01-01T00:00:00Z", reviewer="code-reviewer"),
    expected={"id": "deadbeef0001", "ts": "2026-01-01T00:00:00Z", "in": 500,
              "out": 100, "cache_hit": 50, "source": "provider",
              "card_bytes": 1234, "step": 3, "reviewer": "code-reviewer"},
)
_BASELINE_ESTIMATED = dict(
    kwargs=dict(tokens_in=10, tokens_out=2, cache_hit=5, source="estimated",
                card_bytes=None, attempt_id="deadbeef0002",
                ts="2026-01-01T00:00:00Z"),
    expected={"id": "deadbeef0002", "ts": "2026-01-01T00:00:00Z", "in": 10,
              "out": 2, "cache_hit": 0, "source": "estimated"},
)


@pytest.mark.parametrize("case", [_BASELINE_PROVIDER, _BASELINE_ESTIMATED],
                         ids=["provider", "estimated"])
def test_attempt_written_with_no_new_keys_is_byte_identical_to_pre_ticket_shape(case):
    """AC-8: pin — a caller passing none of the six new keys writes a record
    byte-identical to the pre-KLC-133 shape (D-112 baseline from `main`)."""
    rec = budget_guard.attempt_record(**case["kwargs"])
    assert list(rec.keys()) == list(case["expected"].keys())
    assert rec == case["expected"]
    assert json.dumps(rec) == json.dumps(case["expected"])


def test_provider_attempt_without_card_bytes_never_inherits_the_phases_last_card_size(
        tmp_path, monkeypatch):
    """AC-8: a provider attempt with no card_bytes must not inherit the
    phase's last card size — the carry-forward is non-provider only."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-B1")
    with token_journal.scope("KLC-B1"):
        budget_guard.write_token_metrics("KLC-B1", "review", 10, 2, 0,
                                         source="estimated", card_bytes=999)
        budget_guard.write_token_metrics("KLC-B1", "review", 500, 100, 50,
                                         source="provider", cost_usd=0.01)
    attempts = json.loads(mp.read_text())["metrics"]["tokens"]["review"]["attempts"]
    assert "card_bytes" not in attempts[1]


def test_non_provider_attempt_still_inherits_the_phases_last_card_size(
        tmp_path, monkeypatch):
    """AC-8: pin — a non-provider attempt with no card_bytes still inherits
    the phase's last card size, exactly as before KLC-133."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-B2")
    with token_journal.scope("KLC-B2"):
        budget_guard.write_token_metrics("KLC-B2", "review", 10, 2, 0,
                                         source="estimated", card_bytes=999)
        budget_guard.write_token_metrics("KLC-B2", "review", 20, 4, 0,
                                         source="signal")
    attempts = json.loads(mp.read_text())["metrics"]["tokens"]["review"]["attempts"]
    assert attempts[1]["card_bytes"] == 999


def test_cache_hit_stays_zero_and_cache_write_is_absent_on_a_non_provider_attempt():
    """AC-8/Q-003: cache_hit stays forced to 0 (existing rule) and cache_write
    is absent — never 0 — on a non-provider attempt handed both by mistake."""
    rec = budget_guard.attempt_record(10, 2, 7, "estimated", None,
                                      attempt_id="x", ts="2026-01-01T00:00:00Z",
                                      cache_write=99)
    assert rec["cache_hit"] == 0
    assert "cache_write" not in rec


def test_provider_attempt_stores_every_new_key_in_the_documented_order():
    """AC-8: a provider attempt stores every new key, in the documented
    order (step-10 review-fix: cost_basis added right after cost_usd)."""
    rec = budget_guard.attempt_record(
        500, 100, 50, "provider", 1234, step=3, attempt_id="deadbeef0001",
        ts="2026-01-01T00:00:00Z", reviewer="code-reviewer",
        run_pass="step", cache_write=77, cost_usd=0.05, cost_basis="modelUsage",
        num_turns=3, duration_ms=1500, failed=True)
    assert list(rec.keys()) == [
        "id", "ts", "in", "out", "cache_hit", "source", "card_bytes",
        "step", "reviewer", "run_pass", "cache_write", "cost_usd",
        "cost_basis", "num_turns", "duration_ms", "failed",
    ]
    assert rec["run_pass"] == "step"
    assert rec["cache_write"] == 77
    assert rec["cost_usd"] == 0.05
    assert rec["cost_basis"] == "modelUsage"
    assert rec["num_turns"] == 3
    assert rec["duration_ms"] == 1500
    assert rec["failed"] is True


@pytest.mark.parametrize("source", ["estimated", "signal"])
def test_measured_keys_are_dropped_on_a_non_provider_attempt(source):
    """AC-8: cache_write/cost_usd/cost_basis/num_turns/duration_ms never
    appear on a non-provider attempt, even when a caller passes all five by
    mistake."""
    rec = budget_guard.attempt_record(
        10, 2, 0, source, None, attempt_id="x", ts="2026-01-01T00:00:00Z",
        cache_write=1, cost_usd=2.0, cost_basis="modelUsage", num_turns=3,
        duration_ms=4)
    for key in ("cache_write", "cost_usd", "cost_basis", "num_turns", "duration_ms"):
        assert key not in rec


def test_failed_false_and_empty_run_pass_leave_no_key():
    """AC-8: failed=False and an empty run_pass leave neither key on the record."""
    rec = budget_guard.attempt_record(
        10, 2, 0, "provider", None, attempt_id="x", ts="2026-01-01T00:00:00Z",
        failed=False, run_pass="")
    assert "failed" not in rec
    assert "run_pass" not in rec


def test_attempt_optional_keys_is_the_seven_keys_after_klc133_step10():
    """AC-8/step-10 review-fix ([!DECISION D-118]): ATTEMPT_OPTIONAL_KEYS
    names exactly the seven attempt keys, cost_basis added alongside the
    original six (AC-1 basis-consistency fix)."""
    assert budget_guard.ATTEMPT_OPTIONAL_KEYS == (
        "run_pass", "cache_write", "cost_usd", "cost_basis", "num_turns",
        "duration_ms", "failed")


if __name__ == "__main__":
    test_hard_breach_is_flagged()
    test_soft_breach_warns_not_blocks()
