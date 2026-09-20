#!/usr/bin/env python3
"""KLC-119 step-7 — AC-12: a backfill pass over the archived corpus
reproduces the BEFORE baseline sealed in FACT F-016-F-018 by recording an
`estimated` attempt per stored card, and reruns idempotently.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import metrics  # noqa: E402
import token_backfill  # noqa: E402


def _seed_archived(tmp_path: Path, ticket: str) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "archived", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    return tdir


def test_backfill_over_archived_corpus_reproduces_sealed_baseline_within_five_percent(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)

    total_bytes_expected = 0
    tickets = []
    for i in range(3):
        ticket = f"KLC-{600 + i}"
        _seed_archived(tmp_path, ticket)
        phase_dir = tmp_path / ".klc" / "scratch" / ticket / "discovery"
        phase_dir.mkdir(parents=True)
        text = "x" * (1000 + i * 100)
        (phase_dir / "_prompt.md").write_text(text, encoding="utf-8")
        total_bytes_expected += len(text.encode("utf-8"))
        tickets.append(ticket)

    n_total = sum(token_backfill.backfill_ticket(t, apply=True) for t in tickets)
    assert n_total == 3

    measured_bytes = 0
    for ticket in tickets:
        meta = json.loads(
            (tmp_path / ".klc" / "tickets" / ticket / "meta.json").read_text())
        for _phase, rec in metrics.iter_attempts(meta, ticket):
            measured_bytes += rec.get("card_bytes", 0)

    delta = abs(measured_bytes - total_bytes_expected) / total_bytes_expected
    assert delta <= 0.05, (
        f"backfilled total {measured_bytes} bytes deviates from the "
        f"expected {total_bytes_expected} by more than 5%"
    )


def test_backfill_is_idempotent_and_labels_every_record_estimated(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    ticket = "KLC-610"
    _seed_archived(tmp_path, ticket)
    phase_dir = tmp_path / ".klc" / "scratch" / ticket / "design"
    phase_dir.mkdir(parents=True)
    (phase_dir / "_prompt.md").write_text("hello world", encoding="utf-8")

    n1 = token_backfill.backfill_ticket(ticket, apply=True)
    n2 = token_backfill.backfill_ticket(ticket, apply=True)
    assert n1 == 1 and n2 == 1, "the scan itself always finds the one card"

    meta = json.loads(
        (tmp_path / ".klc" / "tickets" / ticket / "meta.json").read_text())
    attempts = metrics.iter_attempts(meta, ticket)
    design_attempts = [rec for phase, rec in attempts if phase == "design"]
    assert len(design_attempts) == 1, \
        "rerunning the backfill must not create a duplicate attempt (AC-12)"
    assert design_attempts[0]["source"] == "estimated"

    # every backfilled record is estimated — never provider (AC-12 non-goal:
    # no retro-fitted real usage numbers).
    assert all(rec["source"] == "estimated" for _phase, rec in attempts)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
