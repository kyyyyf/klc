"""KLC-077 — unit coverage for the epic-dependency resolver (core/skills/epic_deps.py).

The resolver is pure over meta dicts (plus a caller-supplied upstream reader), so
these tests seed metas directly — no temp .klc, no git. They pin the shared
contract from docs/20260724_epic_feature_impl_plan.md:

  - point → phase-state (track-aware);
  - reached() as an at-or-past position check over config/phases.yml;
  - condition `passed` via STRUCTURED signals (event type + pick.label), never a
    free-text substring scan;
  - blocking_edges() selection by downstream phase;
  - is_blocked() first-unmet-edge with reason (not-reached / condition-failed /
    dangling / cancelled / unreadable), and the empty/absent-blocked_by no-op.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import epic_deps as ed  # noqa: E402


# --- point → phase-state (track-aware) ---------------------------------------

def test_point_to_phase_state_design_accepted_track_aware():
    assert ed.point_to_phase_state("design-accepted", "M") == "design:ack"
    assert ed.point_to_phase_state("design-accepted", "L") == "design:ack"
    assert ed.point_to_phase_state("design-accepted", "S") == "discovery-lite:ack"
    assert ed.point_to_phase_state("design-accepted", "XS") == "discovery-lite:ack"


def test_point_to_phase_state_integrated_and_archived():
    for track in ("XS", "S", "M", "L"):
        assert ed.point_to_phase_state("integrated", track) == "integrate:ack"
        assert ed.point_to_phase_state("archived", track) == "archived"


def test_point_to_phase_state_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        ed.point_to_phase_state("shipped", "M")


# --- reached(): monotonic at-or-past position check --------------------------

def _meta(phase, track="M", **extra):
    m = {"ticket": "UP", "track": track, "phase": phase}
    m.update(extra)
    return m


def test_reached_integrated_before_at_and_past():
    assert ed.reached(_meta("build:ack", track="S"), "integrated") is False
    assert ed.reached(_meta("integrate:work", track="S"), "integrated") is False
    assert ed.reached(_meta("integrate:ack-needed", track="S"), "integrated") is False
    assert ed.reached(_meta("integrate:ack", track="S"), "integrated") is True
    assert ed.reached(_meta("observe:work", track="S"), "integrated") is True
    assert ed.reached(_meta("archived", track="S"), "integrated") is True


def test_reached_design_accepted_track_aware():
    assert ed.reached(_meta("acceptance-test-plan:ack", track="M"),
                      "design-accepted") is False
    assert ed.reached(_meta("design:ack", track="M"), "design-accepted") is True
    assert ed.reached(_meta("build:work", track="M"), "design-accepted") is True
    assert ed.reached(_meta("discovery-lite:ack-needed", track="S"),
                      "design-accepted") is False
    assert ed.reached(_meta("discovery-lite:ack", track="S"),
                      "design-accepted") is True
    assert ed.reached(_meta("build:work", track="S"), "design-accepted") is True


def test_reached_archived_point_only_archived():
    assert ed.reached(_meta("integrate:ack", track="M"), "archived") is False
    assert ed.reached(_meta("learn:work", track="M"), "archived") is False
    assert ed.reached(_meta("archived", track="M"), "archived") is True


def test_reached_cancelled_never_reaches():
    assert ed.reached(_meta("cancelled", track="S"), "integrated") is False
    assert ed.reached(_meta("cancelled", track="M"), "archived") is False


# --- condition_holds(): STRUCTURED signals (event + pick.label) --------------

def test_condition_holds_passed_clean_history():
    up = _meta("archived", track="S", phase_history=[
        {"phase": "build:work", "event": "advance"},
        {"phase": "integrate:ack", "event": "ack",
         "pick": {"id": 1, "label": "merged"}}])
    assert ed.condition_holds("passed", up) is True


def test_condition_holds_benign_note_does_not_over_block():
    # LOW-3: a note MENTIONING "regression tests" must not taint a clean ticket —
    # detection is on the structured pick.label, not the free-text note.
    up = _meta("archived", track="S", phase_history=[
        {"phase": "build:work", "event": "advance",
         "note": "added regression tests for the rollback path",
         "pick": {"id": 1, "label": "approve"}}])
    assert ed.condition_holds("passed", up) is True


def test_condition_holds_fails_on_regression_pick():
    up = _meta("build:work", track="S", phase_history=[
        {"phase": "observe:ack", "event": "ack",
         "pick": {"id": 2, "label": "regression"}}])
    assert ed.condition_holds("passed", up) is False


def test_condition_holds_fails_on_rollback_pick():
    up = _meta("learn:work", track="S", phase_history=[
        {"phase": "learn:work", "event": "ack-jump",
         "pick": {"id": 3, "label": "rollback"}}])
    assert ed.condition_holds("passed", up) is False


def test_condition_holds_fails_on_abort_event():
    up = _meta("build:ack", track="S", phase_history=[
        {"phase": "build:work", "event": "abort", "note": "from=review:work"}])
    assert ed.condition_holds("passed", up) is False


def test_condition_holds_fails_on_jump_event():
    # LOW-3: a backward jump is a rework recorded as event="jump" (no marker word).
    up = _meta("build:work", track="S", phase_history=[
        {"phase": "build:work", "event": "jump", "note": "from=review:ack"}])
    assert ed.condition_holds("passed", up) is False


def test_condition_holds_fails_on_regression_observed_flag():
    up = _meta("archived", track="S", regression_observed=1, phase_history=[
        {"phase": "integrate:ack", "event": "ack",
         "pick": {"id": 1, "label": "merged"}}])
    assert ed.condition_holds("passed", up) is False


def test_condition_holds_unknown_condition_is_not_holding():
    assert ed.condition_holds("green", _meta("archived", track="S",
                                             phase_history=[])) is False


# --- P1-A: legacy pick-note taints (entries written before the `pick` object) -

def test_condition_holds_legacy_note_regression_blocks():
    # An old upstream recorded the pick only in the note, no structured `pick`.
    up = _meta("build:work", track="S", phase_history=[
        {"phase": "observe:ack", "event": "ack", "note": "pick=2:regression"}])
    assert ed.condition_holds("passed", up) is False


def test_condition_holds_legacy_note_rollback_blocks():
    up = _meta("learn:work", track="S", phase_history=[
        {"phase": "learn:work", "event": "ack-jump", "note": "pick=rollback"}])
    assert ed.condition_holds("passed", up) is False


def test_condition_holds_legacy_note_merged_is_clean():
    up = _meta("archived", track="S", phase_history=[
        {"phase": "integrate:ack", "event": "ack", "note": "pick=1:merged"}])
    assert ed.condition_holds("passed", up) is True


def test_condition_holds_legacy_benign_note_not_tainted():
    # A note that merely MENTIONS "regression" but is not a recognised `pick=`
    # token must not taint (no reintroduced substring brittleness).
    up = _meta("archived", track="S", phase_history=[
        {"phase": "build:work", "event": "advance",
         "note": "added regression tests"}])
    assert ed.condition_holds("passed", up) is True


# --- blocking_edges(): select by downstream phase ----------------------------

def _down(*edges, phase="build:ack", track="S"):
    return _meta(phase, track=track, blocked_by=list(edges))


def test_blocking_edges_filters_by_phase():
    e1 = {"on": "UP", "phase": "design", "point": "design-accepted"}
    e2 = {"on": "UP", "phase": "build", "point": "integrated"}
    meta = _down(e1, e2)
    assert ed.blocking_edges(meta, "build") == [e2]
    assert ed.blocking_edges(meta, "design") == [e1]
    assert ed.blocking_edges(meta, "review") == []


def test_blocking_edges_absent_blocked_by_is_empty():
    assert ed.blocking_edges(_meta("build:ack"), "build") == []


# --- is_blocked(): first unmet edge + reason ---------------------------------

def _reader(table):
    def _read(key):
        v = table.get(key, KeyError)
        if v is KeyError:
            return None
        if isinstance(v, Exception):
            raise v
        return v
    return _read


def test_is_blocked_not_reached():
    meta = _down({"on": "UP", "phase": "build", "point": "integrated"})
    b = ed.is_blocked(meta, "build", _reader({"UP": _meta("build:ack", "S")}))
    assert b is not None and b.reason == "not-reached" and b.on == "UP"
    assert "UP" in b.message() and "integrated" in b.message()


def test_is_blocked_unblocks_when_reached():
    meta = _down({"on": "UP", "phase": "build", "point": "integrated"})
    assert ed.is_blocked(meta, "build",
                         _reader({"UP": _meta("archived", "S")})) is None


def test_is_blocked_condition_failed():
    meta = _down({"on": "UP", "phase": "build",
                  "point": "integrated", "condition": "passed"})
    up = _meta("archived", track="S", regression_observed=1)
    b = ed.is_blocked(meta, "build", _reader({"UP": up}))
    assert b is not None and b.reason == "condition-failed"
    assert "human" in b.message().lower()


def test_is_blocked_dangling_upstream():
    meta = _down({"on": "GHOST", "phase": "build", "point": "integrated"})
    b = ed.is_blocked(meta, "build", _reader({}))
    assert b is not None and b.reason == "dangling"
    assert "not found" in b.message()


def test_is_blocked_cancelled_upstream_distinct_message():
    # LOW-5: a cancelled upstream must not read as "until <point>".
    meta = _down({"on": "UP", "phase": "build", "point": "integrated"})
    b = ed.is_blocked(meta, "build",
                      _reader({"UP": _meta("cancelled", "S")}))
    assert b is not None and b.reason == "cancelled"
    assert "cancelled" in b.message() and "will not reach" in b.message()


def test_is_blocked_unreadable_upstream_distinct_from_dangling():
    # LOW-5: a corrupt upstream is "unreadable", not "dangling" (missing).
    meta = _down({"on": "UP", "phase": "build", "point": "integrated"})
    b = ed.is_blocked(meta, "build",
                      _reader({"UP": ed.UpstreamUnreadable("bad json")}))
    assert b is not None and b.reason == "unreadable"
    assert "unreadable" in b.message() or "corrupt" in b.message()


def test_is_blocked_no_edges_is_none():
    assert ed.is_blocked(_meta("build:ack"), "build", _reader({})) is None
    meta = _down({"on": "UP", "phase": "review", "point": "integrated"})
    assert ed.is_blocked(meta, "build",
                         _reader({"UP": _meta("build:ack", "S")})) is None


def test_is_blocked_first_unmet_wins():
    e1 = {"on": "A", "phase": "build", "point": "integrated"}
    e2 = {"on": "B", "phase": "build", "point": "integrated"}
    meta = _down(e1, e2)
    tbl = {"A": _meta("archived", "S"), "B": _meta("build:ack", "S")}
    b = ed.is_blocked(meta, "build", _reader(tbl))
    assert b is not None and b.on == "B"


# --- parse_edge(): --blocked-by spec parsing + validation --------------------

def test_parse_edge_minimal():
    assert ed.parse_edge("KLC-077@design-accepted#design") == {
        "on": "KLC-077", "point": "design-accepted", "phase": "design"}


def test_parse_edge_with_condition():
    assert ed.parse_edge("KLC-077@integrated:passed#build") == {
        "on": "KLC-077", "point": "integrated",
        "condition": "passed", "phase": "build"}


def test_parse_edge_bad_point_hard_fails():
    import pytest
    with pytest.raises(ValueError):
        ed.parse_edge("KLC-077@shipped#build")


def test_parse_edge_bad_condition_hard_fails():
    import pytest
    with pytest.raises(ValueError):
        ed.parse_edge("KLC-077@integrated:green#build")


def test_parse_edge_malformed_shape_hard_fails():
    import pytest
    for bad in ("KLC-077#build", "KLC-077@integrated", "@integrated#build",
                "KLC-077@integrated#", "no-at-no-hash"):
        with pytest.raises(ValueError):
            ed.parse_edge(bad)


def test_parse_edge_self_reference_hard_fails():
    # LOW-4: a ticket cannot depend on itself (a 1-node cycle).
    import pytest
    with pytest.raises(ValueError):
        ed.parse_edge("KLC-078@integrated#build", self_key="KLC-078")
    # A non-self edge with self_key set is fine.
    assert ed.parse_edge("KLC-077@integrated#build", self_key="KLC-078")["on"] \
        == "KLC-077"
