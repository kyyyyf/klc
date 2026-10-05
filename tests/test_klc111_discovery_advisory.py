"""KLC-111 step-7 — an unknown `affected_modules` entry surfaces as one
`medium` advisory record at the discovery and discovery-lite acks, through
the existing `advisories.finish` seam, and never blocks the ack (AC-14,
AC-15, AC-16).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import module_vocabulary as mv  # noqa: E402
import advisories as _adv  # noqa: E402
from phase_completion import (  # noqa: E402
    can_complete_discovery,
    can_complete_discovery_lite,
    _vocabulary_records,
)

MODULES = {"modules": [
    {"name": "core/phases", "path": "core/phases/"},
    {"name": "core/skills", "path": "core/skills/"},
    {"name": "core/agents", "path": "core/agents/"},
]}


def _write_modules(index_dir: Path, data) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        (index_dir / "modules.json").write_text(data, encoding="utf-8")
    else:
        (index_dir / "modules.json").write_text(json.dumps(data), encoding="utf-8")


def _spec_text(ticket: str) -> str:
    return (
        f"---\nticket: {ticket}\nkind: feature\nauthority: agent\n---\n\n"
        "## Goals\nTest.\n\n## Acceptance Criteria\n- AC-1: pass.\n\n"
        "## Estimate\ncomplexity: 1\n\n"
        "## Approaches\n- Option A: first approach\n- Option B: second approach\n\n"
        "Picked: Option A — simpler\n"
    )


def _seed_m_ticket(tmp_path: Path, ticket: str, affected_modules: list) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    (tdir / "spec.md").write_text(_spec_text(ticket), encoding="utf-8")
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery:work",
        "track": "M", "route_hint": "M",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
        "affected_modules": affected_modules, "layer": "code",
    }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return tdir


def _seed_s_ticket(tmp_path: Path, ticket: str, affected_modules: list) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    spec = (
        f"---\nticket: {ticket}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n\n"
        "## Goals\nTest.\n\n## Acceptance Criteria\n- [ ] AC-1: pass.\n\n"
        "## Affected\ntest_module: core/test.py, src=core/test.py:1\n\n"
        "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n"
    )
    (tdir / "spec.md").write_text(spec, encoding="utf-8")
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery-lite:work",
        "track": "S",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "affected_modules": affected_modules, "layer": "code",
    }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (tdir / "options-lite.md").write_text(
        "- Option A: fast impl\n- Option B: safer impl\nPicked: Option A — lower risk\n",
        encoding="utf-8")
    (tdir / "impl-plan.md").write_text(
        "## step-1 — do the thing\n\n- **Goal:** implement\n- RED: not applicable\n"
        "- **Interfaces:** `def f() -> None`\n- **Expected:** f runs\n"
        "- **VERIFY:** pytest\n- **COMMIT:** KLC-X step-1: do the thing\n"
        "- **Affected:** src/x.py\n", encoding="utf-8")
    return tdir


def test_can_complete_discovery_emits_one_medium_advisory_per_unknown_affected_module(
        tmp_path, monkeypatch):
    """AC-14: `can_complete_discovery` emits one `medium` advisory record per
    `affected_modules` entry outside the vocabulary, through
    `advisories.finish`'s `_sources` list."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_modules(tmp_path / ".klc" / "index", MODULES)
    ticket = "KLC-D01"
    _seed_m_ticket(tmp_path, ticket, ["core/phases", "totally_unknown_name"])

    ok, _summary = can_complete_discovery(ticket)
    assert ok
    envelope = _adv.read(ticket, "discovery")
    records = [r for r in envelope["records"] if r["source"] == "scope-vocabulary"]
    assert len(records) == 1, records
    assert records[0]["severity"] == "medium"
    assert records[0]["ref"] == "totally_unknown_name"


def test_can_complete_discovery_lite_emits_one_medium_advisory_per_unknown_affected_module(
        tmp_path, monkeypatch):
    """AC-14: the same producer is wired at the discovery-lite ack site."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_modules(tmp_path / ".klc" / "index", MODULES)
    ticket = "KLC-D02"
    _seed_s_ticket(tmp_path, ticket, ["core/phases", "another_unknown_name"])

    ok, _summary = can_complete_discovery_lite(ticket)
    assert ok
    envelope = _adv.read(ticket, "discovery-lite")
    records = [r for r in envelope["records"] if r["source"] == "scope-vocabulary"]
    assert len(records) == 1, records
    assert records[0]["severity"] == "medium"
    assert records[0]["ref"] == "another_unknown_name"


def test_unknown_module_advisory_never_blocks_discovery_ack(tmp_path, monkeypatch):
    """AC-14 negative twin: an unknown module name never blocks the ack —
    `can_complete_discovery` still returns `(True, ...)`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_modules(tmp_path / ".klc" / "index", MODULES)
    ticket = "KLC-D03"
    _seed_m_ticket(tmp_path, ticket, ["nonexistent_module_one", "nonexistent_module_two"])
    ok, summary = can_complete_discovery(ticket)
    assert ok is True, summary


def test_advisory_message_names_nearest_in_vocabulary_match_within_threshold(tmp_path, monkeypatch):
    """AC-15 (test-plan N-3): the advisory message names the nearest
    in-vocabulary candidate — `nearest("phases", vocab) == "core/phases"`
    per D-010's own worked example (tier-1: last-segment equality), not the
    stale test-plan example naming `core/skills`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_modules(tmp_path / ".klc" / "index", MODULES)
    ticket = "KLC-D04"
    _seed_m_ticket(tmp_path, ticket, ["phases"])
    assert mv.nearest("phases", mv.vocabulary(MODULES)) == "core/phases"

    records = _vocabulary_records(ticket)
    assert len(records) == 1
    assert "core/phases" in records[0]["message"]


def test_advisory_message_states_no_candidate_found_when_nothing_within_threshold(
        tmp_path, monkeypatch):
    """AC-15 negative twin: a name with no close match states plainly that
    none was found, rather than naming a misleading candidate."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_modules(tmp_path / ".klc" / "index", MODULES)
    ticket = "KLC-D05"
    _seed_m_ticket(tmp_path, ticket, ["zzz_completely_unrelated_xyz"])
    assert mv.nearest("zzz_completely_unrelated_xyz", mv.vocabulary(MODULES)) is None

    records = _vocabulary_records(ticket)
    assert len(records) == 1
    assert "no" in records[0]["message"].lower()
    assert "found" in records[0]["message"].lower()


def test_missing_modules_json_degrades_to_one_info_advisory_naming_reason(tmp_path, monkeypatch):
    """AC-16: a missing `modules.json` degrades to exactly one `info`
    advisory record naming the reason, so a stale/absent index never fails
    a discovery ack."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-D06"
    _seed_m_ticket(tmp_path, ticket, ["core/phases"])
    records = _vocabulary_records(ticket)
    assert len(records) == 1
    assert records[0]["severity"] == "info"
    assert "not found" in records[0]["message"]


def test_unreadable_or_no_modules_list_modules_json_degrades_to_one_info_advisory(
        tmp_path, monkeypatch):
    """AC-16: malformed JSON, and a well-formed dict with no `modules` list,
    both degrade to exactly one `info` advisory record."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-D07"
    _seed_m_ticket(tmp_path, ticket, ["core/phases"])

    _write_modules(tmp_path / ".klc" / "index", "{ not json")
    records = _vocabulary_records(ticket)
    assert len(records) == 1 and records[0]["severity"] == "info"

    _write_modules(tmp_path / ".klc" / "index", {"generated_at": "x"})
    records2 = _vocabulary_records(ticket)
    assert len(records2) == 1 and records2[0]["severity"] == "info"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
