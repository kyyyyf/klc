#!/usr/bin/env python3
"""KLC-174 step-5 / AC-8: the card-size budget gate is replaced by a
WARN-ONLY check over REAL spend. `budget_guard.real_spend_warning(track,
ticket=...)` compares the current ticket's measured input tokens (source
`provider` / `transcript`) with 1.5x the median of the last N archived
tickets of the same track. It never blocks, and a card render writes no
`estimated` attempt any more.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "core" / "phases"))

import budget_guard  # noqa: E402
import token_journal  # noqa: E402


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    monkeypatch.setattr(token_journal, "_IGNORE_ENSURED", False)
    monkeypatch.setattr(token_journal, "_OPEN", set())


def _ticket(tmp_path, key, *, phase="archived", track="S", totals=(),
            source="transcript"):
    tdir = tmp_path / ".klc" / "tickets" / key
    tdir.mkdir(parents=True)
    attempts = [{"id": f"{key}-{i}", "in": t, "out": 1, "cache_hit": 0,
                 "source": source} for i, t in enumerate(totals)]
    meta = {"ticket": key, "kind": "tech", "phase": phase, "track": track,
            "phase_history": [], "affected_modules": [],
            "metrics": {"tokens": {"build": {"attempts": attempts}}} if attempts else {}}
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _corpus(tmp_path, per_ticket=(100, 200, 300)):
    for i, total in enumerate(per_ticket, start=1):
        _ticket(tmp_path, f"KLC-90{i}", totals=[total])


def test_median_from_archived_corpus_and_warning_above_1_5x(tmp_path):
    _corpus(tmp_path)                      # median 200 -> threshold 300
    _ticket(tmp_path, "KLC-950", phase="build:work", totals=[200, 150])  # 350
    msg = budget_guard.real_spend_warning("S", ticket="KLC-950")
    assert msg and "350" in msg and "200" in msg and "\n" not in msg


def test_no_warning_below_threshold(tmp_path):
    _corpus(tmp_path)
    _ticket(tmp_path, "KLC-950", phase="build:work", totals=[250])
    assert budget_guard.real_spend_warning("S", ticket="KLC-950") is None


def test_no_warning_without_measured_data(tmp_path):
    # corpus exists but only `estimated` records, and the current ticket has none
    for i in range(3):
        _ticket(tmp_path, f"KLC-90{i}", totals=[9999], source="estimated")
    _ticket(tmp_path, "KLC-950", phase="build:work", totals=[9999])
    assert budget_guard.real_spend_warning("S", ticket="KLC-950") is None
    # no corpus at all
    assert budget_guard.real_spend_warning("L", ticket="KLC-950") is None
    # no ticket given
    assert budget_guard.real_spend_warning("S") is None


def test_other_track_and_unarchived_tickets_do_not_feed_the_median(tmp_path):
    _corpus(tmp_path, (100, 100, 100))
    _ticket(tmp_path, "KLC-920", track="M", totals=[10_000_000])
    _ticket(tmp_path, "KLC-921", phase="build:work", totals=[10_000_000])
    _ticket(tmp_path, "KLC-950", phase="build:work", totals=[140])
    assert budget_guard.real_spend_warning("S", ticket="KLC-950") is None


def test_window_takes_only_the_last_n_archived(tmp_path, monkeypatch):
    monkeypatch.setattr(budget_guard, "load_real_spend_config",
                        lambda: {"window": 3, "factor": 1.5})
    for i, total in enumerate((1_000_000, 1_000_000, 100, 100, 100), start=1):
        _ticket(tmp_path, f"KLC-90{i}", totals=[total])
    _ticket(tmp_path, "KLC-950", phase="build:work", totals=[200])
    assert budget_guard.real_spend_warning("S", ticket="KLC-950")


def test_removed_gate_api_is_gone():
    for name in ("check_prompt_budget", "gate_card_dispatch",
                 "find_second_estimators", "estimate_tokens",
                 "estimate_tokens_from_bytes", "BudgetVerdict"):
        assert not hasattr(budget_guard, name), name


def test_budgets_yml_documents_the_knob_and_drops_card_limits():
    import yaml
    data = yaml.safe_load((FW_ROOT / "config" / "budgets.yml").read_text(
        encoding="utf-8"))
    assert "hard_limits" not in data and "soft_limits" not in data
    assert data["real_spend_warn"]["factor"] == 1.5
    assert isinstance(data["real_spend_warn"]["window"], int)


def test_card_render_writes_no_estimated_attempt(tmp_path):
    import artefacts
    _ticket(tmp_path, "KLC-960", phase="review:work", track="M")
    (tmp_path / ".klc" / "tickets" / "KLC-960" / "spec.md").write_text(
        "## Goals\nx\n## Acceptance Criteria\n- AC-1\n", encoding="utf-8")
    meta = json.loads((tmp_path / ".klc" / "tickets" / "KLC-960"
                       / "meta.json").read_text(encoding="utf-8"))
    render = artefacts.render_card("KLC-960", "review", meta)
    assert render.card_bytes > 0
    assert [r for r in token_journal.read("KLC-960")] == []
    after = json.loads((tmp_path / ".klc" / "tickets" / "KLC-960"
                        / "meta.json").read_text(encoding="utf-8"))
    assert not (after.get("metrics") or {}).get("tokens")


def test_no_estimated_writer_remains_in_core():
    import re
    pat = re.compile(r'source\s*=\s*["\']estimated["\']')
    hits = [str(p) for p in (FW_ROOT / "core").rglob("*.py")
            if pat.search(p.read_text(encoding="utf-8"))]
    assert hits == []


def test_old_estimated_records_still_read_by_the_rollup(tmp_path):
    import metrics
    _ticket(tmp_path, "KLC-970", totals=[500], source="estimated")
    meta = json.loads((tmp_path / ".klc" / "tickets" / "KLC-970"
                       / "meta.json").read_text(encoding="utf-8"))
    pairs = metrics.iter_attempts(meta, "KLC-970")
    assert [r["source"] for _p, r in pairs] == ["estimated"]
    assert "estimated" in metrics._SOURCES
