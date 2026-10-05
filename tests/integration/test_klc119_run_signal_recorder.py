#!/usr/bin/env python3
"""KLC-119 step-5 — AC-3: `run_signal.record_signal_tokens` — a `signal`
attempt when the completion signal carries usage, an `estimated` attempt
from the dispatch card otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import run_signal  # noqa: E402
import token_journal  # noqa: E402


def _seed(tmp_path: Path, ticket: str) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "build:work", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")


class _FakeCardRender:
    est_tokens = 55
    card_bytes = 220


def test_signal_tokens_present_records_source_signal_absent_falls_back_to_estimated_from_card(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-500"
    _seed(tmp_path, ticket)

    signal_with_tokens = run_signal.Signal(
        phase="build", signal="done", artifacts=[], blocking_questions=[],
        next_action="ack", tokens={"in": 111, "out": 22})
    src = run_signal.record_signal_tokens(signal_with_tokens, ticket, "build")
    assert src == "signal"
    records = [r for r in token_journal.read(ticket) if r.get("phase") == "build"]
    assert records and records[-1]["source"] == "signal"
    assert records[-1]["in"] == 111 and records[-1]["out"] == 22

    signal_no_tokens = run_signal.Signal(
        phase="build", signal="done", artifacts=[], blocking_questions=[],
        next_action="ack", tokens=None)
    src2 = run_signal.record_signal_tokens(
        signal_no_tokens, ticket, "build", card_render=_FakeCardRender())
    assert src2 is None            # KLC-174: no `estimated` fallback
    records2 = [r for r in token_journal.read(ticket) if r.get("phase") == "build"]
    assert len(records2) == 1 and records2[-1]["source"] == "signal"

    # a malformed tokens block (not a dict, or missing "in") is treated as
    # absent — records nothing, never raises.
    signal_malformed = run_signal.Signal(
        phase="build", signal="done", artifacts=[], blocking_questions=[],
        next_action="ack", tokens={"out": 5})
    src3 = run_signal.record_signal_tokens(
        signal_malformed, ticket, "build", card_render=_FakeCardRender())
    assert src3 is None
    assert len([r for r in token_journal.read(ticket)
                if r.get("phase") == "build"]) == 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
