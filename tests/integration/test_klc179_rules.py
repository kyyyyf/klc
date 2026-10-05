"""KLC-179 step-1 (AC-1): the ordered rule table is total over the fact lattice.

`rules.next_move(facts, track, risk_tags=...)` is pure: the property test walks
every true/false combination of the ten facts on both lanes with risk tags on
and off. The expected required-fact lists are written out here on purpose
(operator decision D-001), so a drift in the module's own table is caught.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (_FW, _FW / "core" / "skills"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import rules  # noqa: E402

FULL_ORDER = ("spec_approved", "test_plan_approved", "design_approved", "plan_reviewed",
              "steps_green", "review_verdict", "manual_passed", "merged",
              "observed", "retro_written")
GATE_FACTS = set(FULL_ORDER)
DECISION = {"light": {"spec_approved"},
            "full": {"spec_approved", "design_approved", "manual_passed"}}
TAGS = (["user-facing"], [])


def _required(lane: str, risk_tags: list, retro: bool = False) -> list:
    if lane == "light":
        req = ["spec_approved", "plan_reviewed", "steps_green", "review_verdict", "merged"]
        if retro:
            req.append("retro_written")
        return req
    req = ["spec_approved", "test_plan_approved", "design_approved", "plan_reviewed",
           "steps_green", "review_verdict"]
    if risk_tags:
        req.append("manual_passed")
    req.append("merged")
    if risk_tags:
        req.append("observed")
    req.append("retro_written")
    return req


def _facts(bits, retro: bool = False) -> dict:
    facts = {n: b for n, b in zip(FULL_ORDER, bits)}
    facts["review_verdict"] = "APPROVED" if facts["review_verdict"] else None
    if retro:
        facts["retro_required"] = True
    return facts


def test_fact_order_is_the_decided_one():
    assert tuple(rules.FACT_ORDER) == FULL_ORDER
    assert set(rules.FACTS) == GATE_FACTS


@pytest.mark.parametrize("lane", ["light", "full"])
@pytest.mark.parametrize("risk_tags", TAGS, ids=["tags", "no-tags"])
@pytest.mark.parametrize("retro", [False, True])
def test_next_move_total_over_fact_lattice(lane, risk_tags, retro):
    seen_archive = 0
    for bits in itertools.product((False, True), repeat=len(FULL_ORDER)):
        facts = _facts(bits, retro)
        move = rules.next_move(facts, lane, risk_tags=risk_tags)
        assert isinstance(move, rules.Move)
        required = _required(lane, risk_tags, retro)
        missing = [f for f in required if not rules.holds(facts, f)]
        if move.action == "archive":
            seen_archive += 1
            assert not missing, f"archive with missing gate facts {missing}: {facts}"
        else:
            # first missing required fact wins
            assert move.fact == missing[0], (lane, facts, move)
        assert (move.fact in DECISION[lane]) == move.stop if move.fact else not move.stop
        assert move.blocked_on in (None, *DECISION[lane])
        if move.blocked_on:
            assert move.blocked_on == move.fact and move.stop
    assert seen_archive >= 1   # the all-true corner is reachable


@pytest.mark.parametrize("lane", ["light", "full"])
def test_clean_run_stops_only_at_decision_points(lane):
    facts: dict = {}
    stops = []
    for _ in range(20):
        move = rules.next_move(facts, lane, risk_tags=["data"])
        if move.action == "archive":
            break
        if move.stop:
            stops.append(move.fact)
        facts[move.fact] = "APPROVED" if move.fact == "review_verdict" else True
    assert move.action == "archive"
    assert stops == (["spec_approved"] if lane == "light"
                     else ["spec_approved", "design_approved", "manual_passed"])


def test_actions_and_phases_pinned():
    m = rules.next_move({}, "light", risk_tags=[])
    assert (m.action, m.phase, m.stop) == ("spec", "discovery-lite", True)
    m = rules.next_move({}, "full", risk_tags=[])
    assert (m.action, m.phase, m.stop) == ("spec", "discovery", True)
    m = rules.next_move({"spec_approved": True}, "full", risk_tags=[])
    assert (m.action, m.phase, m.stop) == ("test-plan", "acceptance-test-plan", False)
    m = rules.next_move({"spec_approved": True, "test_plan_approved": True}, "full", risk_tags=[])
    assert (m.action, m.phase, m.stop) == ("design", "design", True)
    done = {n: True for n in FULL_ORDER}
    done["review_verdict"] = "APPROVED"
    assert rules.next_move(done, "full", risk_tags=["data"]).action == "archive"


def test_plan_reviewed_follows_design_on_full_and_spec_on_light():
    full = {"spec_approved": True, "test_plan_approved": True, "design_approved": True}
    assert rules.next_move(full, "full", risk_tags=[]).fact == "plan_reviewed"
    assert rules.next_move({"spec_approved": True}, "light", risk_tags=[]).fact == "plan_reviewed"


def test_all_gates_but_merged_means_integrate_not_archive():
    done = {n: True for n in FULL_ORDER}
    done["review_verdict"] = "APPROVED"
    done["merged"] = False
    for lane in ("light", "full"):
        m = rules.next_move(done, lane, risk_tags=["data"])
        assert (m.action, m.phase) == ("integrate", "integrate")


def test_changes_requested_sends_back_to_build():
    facts = {n: True for n in FULL_ORDER[:5]}
    facts["review_verdict"] = "CHANGES_REQUESTED"
    for lane in ("light", "full"):
        m = rules.next_move(facts, lane, risk_tags=[])
        assert (m.action, m.phase) == ("build", "build")


def test_empty_risk_tags_skip_manual_and_observe_nonempty_require_them():
    base = {n: True for n in FULL_ORDER}
    base["review_verdict"] = "APPROVED"
    base["manual_passed"] = False
    assert rules.next_move(base, "full", risk_tags=[]).action == "archive"
    assert rules.next_move(base, "full", risk_tags=["data"]).fact == "manual_passed"
    base["manual_passed"], base["observed"] = True, False
    assert rules.next_move(base, "full", risk_tags=[]).action == "archive"
    assert rules.next_move(base, "full", risk_tags=["data"]).fact == "observed"


def test_light_retro_only_on_overrun_or_regression():
    facts = {n: True for n in FULL_ORDER}
    facts["review_verdict"] = "APPROVED"
    facts["retro_written"] = False
    assert rules.next_move(facts, "light", risk_tags=[]).action == "archive"
    facts["retro_required"] = True
    assert rules.next_move(facts, "light", risk_tags=[]).fact == "retro_written"
    facts["retro_required"] = False
    assert rules.next_move(facts, "full", risk_tags=[]).fact == "retro_written"


@pytest.mark.parametrize("bad", ["yes", 1, 0, "true", [], {}, None, "CHANGES_REQUESTED"])
def test_malformed_fact_values_count_as_missing(bad):
    done = {n: True for n in FULL_ORDER}
    done["review_verdict"] = "APPROVED"
    for name in ("spec_approved", "steps_green", "merged"):
        facts = {**done, name: bad}
        for lane in ("light", "full"):
            m = rules.next_move(facts, lane, risk_tags=[])
            assert m.action != "archive"
            assert m.fact == name
    assert rules.next_move({**done, "review_verdict": bad}, "full", risk_tags=[]).action != "archive"


def test_unknown_track_and_garbage_inputs_fail_closed_to_full():
    assert rules.next_move({}, "weird", risk_tags=[]).phase == "discovery"
    assert rules.next_move({"spec_approved": True}, "M", risk_tags=[]).fact == "test_plan_approved"
    assert rules.next_move({"spec_approved": True}, "S", risk_tags=[]).fact == "plan_reviewed"
    assert rules.next_move({}, "light", risk_tags=None).action == "spec"


def test_terminal_facts_return_done_never_a_work_move():
    for terminal in ("cancelled", "archived"):
        m = rules.next_move({"terminal": terminal}, "full", risk_tags=["data"])
        assert m.action == "done" and not m.stop and m.fact is None


def test_legacy_track_mapping():
    assert [rules.legacy_track(t) for t in ("XS", "S", "M", "L")] == ["light", "light", "full", "full"]
    assert rules.legacy_track(None) == "full" and rules.legacy_track("??") == "full"
    assert rules.lane_letter("light") == "S" and rules.lane_letter("full") == "M"
    assert rules.legacy_track(rules.lane_letter("light")) == "light"
    assert rules.legacy_track(rules.lane_letter("full")) == "full"
