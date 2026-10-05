"""KLC-179 step-1 (AC-3): facts are derived in memory from legacy metas.

The fixtures under tests/fixtures/klc179-corpus are trimmed copies of the
KLC-154 and KLC-166 meta shapes (full lane, archived), an XS ticket (KLC-040)
and a cancelled ticket (KLC-004). Derivation reads, never writes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (_FW, _FW / "core" / "skills"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import rules  # noqa: E402

CORPUS = _FW / "tests" / "fixtures" / "klc179-corpus"


def _load(key):
    return json.loads((CORPUS / key / "meta.json").read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _all_files():
    return sorted(p for p in CORPUS.rglob("*") if p.is_file())


def test_derive_facts_on_legacy_corpus():
    before = {p: _digest(p) for p in _all_files()}
    for key in ("KLC-154", "KLC-166", "KLC-040", "KLC-004"):
        meta = _load(key)
        snapshot = copy.deepcopy(meta)
        facts = rules.derive_facts(meta, CORPUS / key)
        assert "facts" not in meta and meta == snapshot      # no mutation
        assert meta["phase"] == snapshot["phase"]
        assert isinstance(facts, dict)
    assert {p: _digest(p) for p in _all_files()} == before   # bytes untouched


def test_full_archived_ticket_with_risk_tags_derives_every_fact():
    meta = _load("KLC-154")
    assert "integrate" not in meta                            # merged comes from the phase
    facts = rules.derive_facts(meta, CORPUS / "KLC-154")
    assert facts["terminal"] == "archived" and facts["merged"] is True
    assert facts["review_verdict"] == "APPROVED"              # from review-report.md
    for name in rules.FACT_ORDER:
        assert rules.holds(facts, name), name
    assert rules.next_move(facts, rules.legacy_track(meta["track"]),
                           risk_tags=meta["risk_tags"]).action == "done"


def test_full_archived_ticket_with_skipped_observe():
    meta = _load("KLC-166")
    facts = rules.derive_facts(meta)                          # no ticket dir: verdict from the ack
    assert facts["merged"] is True and facts["terminal"] == "archived"
    assert facts["review_verdict"] == "APPROVED"
    assert facts["manual_passed"] is True
    assert rules.holds(facts, "observed")                     # observe was skipped: not required
    assert rules.holds(facts, "design_approved") and rules.holds(facts, "test_plan_approved")


def test_xs_ticket_is_light_and_merged():
    meta = _load("KLC-040")
    assert rules.legacy_track(meta["track"]) == "light"
    facts = rules.derive_facts(meta)
    assert facts["merged"] is True and facts["terminal"] == "archived"
    assert rules.holds(facts, "steps_green") and rules.holds(facts, "review_verdict")
    assert rules.holds(facts, "plan_reviewed")
    assert rules.next_move(facts, "light", risk_tags=[]).action == "done"


def test_cancelled_ticket_is_terminal_and_not_merged():
    for meta in (_load("KLC-004"), {"ticket": "KLC-005", "phase": "cancelled"}):
        facts = rules.derive_facts(meta)
        assert facts["terminal"] == "cancelled"
        assert not rules.holds(facts, "merged")
        m = rules.next_move(facts, rules.legacy_track(meta.get("track")), risk_tags=[])
        assert m.action == "done" and not m.stop


def test_in_flight_light_ticket_at_build():
    meta = {"track": "S", "phase": "build:work", "phase_history": [
        {"phase": "intake:ack-needed"},
        {"phase": "intake:ack", "event": "ack", "pick": {"id": 1, "label": "confirm-route"}},
        {"phase": "discovery-lite:work", "event": "advance"},
        {"phase": "discovery-lite:ack-needed", "event": "manual-completion"},
        {"phase": "discovery-lite:ack", "event": "ack", "pick": {"id": 1, "label": "approve"}},
        {"phase": "build:work", "event": "advance"}]}
    facts = rules.derive_facts(meta)
    assert rules.holds(facts, "spec_approved") and rules.holds(facts, "plan_reviewed")
    assert not rules.holds(facts, "steps_green") and "terminal" not in facts
    m = rules.next_move(facts, rules.legacy_track("S"), risk_tags=[])
    assert (m.action, m.fact) == ("build", "steps_green")


def test_rework_picks_do_not_set_the_fact_and_clear_downstream():
    def ack(phase, label):
        return {"phase": f"{phase}:ack", "event": "ack", "pick": {"id": 2, "label": label}}
    ok = lambda phase: {"phase": f"{phase}:ack", "event": "ack", "pick": {"id": 1, "label": "approve"}}  # noqa: E731
    meta = {"track": "M", "phase": "build:work", "phase_history": [
        ok("discovery"), ok("acceptance-test-plan"), ok("design"), ok("build"), ok("review"),
        ack("review", "request-changes"), {"phase": "build:work", "event": "advance"}]}
    facts = rules.derive_facts(meta)
    assert rules.holds(facts, "design_approved")
    assert not rules.holds(facts, "steps_green") and not rules.holds(facts, "review_verdict")
    assert rules.next_move(facts, "full", risk_tags=[]).action == "build"


def test_existing_facts_key_wins_and_is_returned_as_a_copy():
    meta = {"track": "S", "phase": "build:work", "facts": {"spec_approved": True}}
    facts = rules.derive_facts(meta)
    assert facts["spec_approved"] is True
    facts["merged"] = True
    assert meta["facts"] == {"spec_approved": True}


def test_garbage_meta_never_raises():
    for meta in ({}, {"phase": None}, {"phase_history": "x"}, {"phase_history": [None, 3, {"phase": 7}]},
                 {"phase": "build:work", "phase_history": [{"phase": "design:ack", "event": "ack", "pick": "bad"}]}):
        assert isinstance(rules.derive_facts(meta), dict)
