#!/usr/bin/env python3
"""tests/test_epic_view.py — unit tests for epic_view.py (KLC-078).

Pure-logic epic view: epic state, ready-set, cycle/dangling/dead-edge
validation. The milestone/condition "reached/blocked" semantics are delegated
to KLC-077's `epic_deps` (the single resolver, now on main) — these tests seed
member metas whose phases exercise that real resolver, and one test asserts the
delegation wiring directly.

`compute_epic(root, all_metas, ...)` takes EVERY repo ticket's meta (membership
is computed inside from `meta.epic == root`), so a cross-epic dependency
resolves like the live guard. No filesystem / subprocess — metas are plain dicts.

Run:  python -m pytest tests/test_epic_view.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import epic_view  # noqa: E402
import epic_deps  # noqa: E402


ROOT = "KLC-077"


def _m(key, phase, *, track="M", epic=ROOT, blocked_by=None, holder=None,
       phase_history=None):
    meta = {"ticket": key, "phase": phase, "track": track, "epic": epic}
    if blocked_by is not None:
        meta["blocked_by"] = blocked_by
    if holder is not None:
        meta["holder"] = holder
    if phase_history is not None:
        meta["phase_history"] = phase_history
    return meta


def _repo(*metas):
    """Build an all_metas dict from ticket metas."""
    return {m["ticket"]: m for m in metas}


# --- epic state ---------------------------------------------------------------

def test_state_planned_all_intake():
    repo = _repo(
        _m(ROOT, "intake:ack-needed"),
        _m("KLC-078", "intake:ack-needed"),
    )
    members = {k: v for k, v in repo.items()}
    assert epic_view.epic_state(members) == epic_view.STATE_PLANNED


def test_state_in_progress_any_past_intake():
    members = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "intake:ack-needed"),
    )
    assert epic_view.epic_state(members) == epic_view.STATE_IN_PROGRESS


def test_state_done_all_terminal():
    members = _repo(
        _m(ROOT, "archived"),
        _m("KLC-078", "cancelled"),
    )
    assert epic_view.epic_state(members) == epic_view.STATE_DONE


def test_state_cancelled_plus_intake_is_in_progress():
    members = _repo(
        _m(ROOT, "cancelled"),
        _m("KLC-078", "intake:ack-needed"),
    )
    assert epic_view.epic_state(members) == epic_view.STATE_IN_PROGRESS


# --- ready set / blocked (resolver = epic_deps) -------------------------------

def test_ready_set_excludes_blocked_member():
    # KLC-078 gated at build by KLC-077 @ design-accepted; KLC-078 sits at
    # design:ack so build IS its immediate next :work entry; upstream still in
    # design:work -> not reached -> KLC-078 blocked, KLC-077 ready.
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "design:ack", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me@host")
    assert rep.ready == [ROOT]
    assert rep.blocked == ["KLC-078"]


# --- P2: an unmet edge gating a FUTURE phase is not a current blocker ---------

def test_future_phase_gate_does_not_block_early_work():
    # (a) KLC-078 is at design:work with an unmet edge gating `build` (a later
    # phase). Its immediate next :work move stays inside design, so per live
    # enforcement it is actionable NOW -> READY, with the gate noted as upcoming.
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "design:work", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.ready, rep.blocked
    assert "KLC-078" not in rep.blocked
    v = next(m for m in rep.members if m.key == "KLC-078")
    assert v.unmet == []                 # no CURRENT blocker
    assert any(e.phase == "build" for e in v.upcoming), v.upcoming


def test_same_member_blocked_once_build_is_next_work():
    # (b) The SAME edge, but KLC-078 has advanced to design:ack so `build` IS
    # its next :work entry -> now BLOCKED (upstream still not reached).
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "design:ack", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.blocked
    assert "KLC-078" not in rep.ready


def test_edge_gating_immediate_next_phase_blocks_now():
    # (c) Unchanged behaviour: an edge gating the member's IMMEDIATE next phase
    # (intake:ack -> discovery) blocks it right now.
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "intake:ack", blocked_by=[
            {"on": ROOT, "phase": "discovery", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.blocked


# --- P2 (round 2): the next :work entry honours conditional-phase skips -------
# M-track at integrate:ack with no risk_tags: observe is SKIPPED, so advance
# enters `learn`. The view must gate on `learn`, not the skipped `observe`.

def test_edge_on_skipped_phase_does_not_block():
    # (a) an unmet edge gating the SKIPPED phase (observe) never fires -> the
    # member is NOT blocked (dead edge), and it is warned.
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "integrate:ack", track="M", blocked_by=[
            {"on": ROOT, "phase": "observe", "point": "integrated"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" not in rep.blocked
    assert "KLC-078" in rep.ready
    assert any("dead edge" in w and "observe" in w for w in rep.warnings), \
        rep.warnings


def test_edge_on_actual_next_entry_after_skip_blocks():
    # (b) an unmet edge gating the ACTUAL next entered phase (learn, since
    # observe is skipped) blocks now.
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "integrate:ack", track="M", blocked_by=[
            {"on": ROOT, "phase": "learn", "point": "integrated"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.blocked


def test_view_next_entry_matches_lifecycle_skip():
    # The view's next-entry equals what advance_to_next actually enters across a
    # conditional skip: integrate:ack, no risk_tags -> observe skipped -> learn.
    import copy
    import lifecycle

    meta = {"ticket": "KLC-078", "phase": "integrate:ack", "track": "M",
            "phase_history": []}
    # pure resolution used by the view
    assert lifecycle.next_work_phase(copy.deepcopy(meta)) == "learn"

    # advance_to_next (the live path) agrees, over an in-memory meta store
    store = {"KLC-078": copy.deepcopy(meta)}

    def _read(t, **kw):
        return copy.deepcopy(store[t])

    def _write(t, m):
        store[t] = copy.deepcopy(m)

    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(lifecycle, "read_meta", _read)
    mp.setattr(lifecycle, "write_meta", _write)
    mp.setattr(lifecycle, "_jira_push_after_state", lambda *a, **k: None)
    try:
        new_state = lifecycle.advance_to_next("KLC-078")
    finally:
        mp.undo()
    assert new_state == "learn:work"
    # observe was recorded as skipped, learn entered
    events = [(e.get("phase"), e.get("event"))
              for e in store["KLC-078"]["phase_history"]]
    assert ("observe:work", "skipped") in events, events
    assert store["KLC-078"]["phase"] == "learn:work"


# --- P2-A: :ack-needed auto-advances -> gate the same as :ack ------------------

def test_ack_needed_blocked_when_next_entry_gated():
    # An `ack` at intake:ack-needed with a goto:next pick auto-advances straight
    # into discovery:work (and enter_work_guard fires). So an unmet edge gating
    # discovery must block NOW, not be hidden as ready.
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "intake:ack-needed", blocked_by=[
            {"on": ROOT, "phase": "discovery", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.blocked, rep.ready


def test_ack_needed_later_gate_is_upcoming():
    # From :ack-needed, an edge on a LATER phase is still upcoming (not current).
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "intake:ack-needed", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.ready
    v = next(m for m in rep.members if m.key == "KLC-078")
    assert any(e.phase == "build" for e in v.upcoming), v.upcoming


def test_work_state_has_no_imminent_gate():
    # A ticket already INSIDE a work phase has no imminent :work entry, so it is
    # actionable now even if an edge names its current phase.
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "discovery:work", blocked_by=[
            {"on": ROOT, "phase": "discovery", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.ready
    assert "KLC-078" not in rep.blocked


def test_blocked_becomes_ready_when_point_reached():
    repo = _repo(
        _m(ROOT, "design:ack"),
        _m("KLC-078", "design:ack", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me@host")
    assert set(rep.ready) == {ROOT, "KLC-078"}
    assert rep.blocked == []


def test_edge_moot_after_gated_phase_entered():
    # KLC-078 already at build:work (entered the gated phase); the build edge no
    # longer stands even though upstream never reached the point.
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "build:work", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me@host")
    assert "KLC-078" in rep.ready
    assert rep.blocked == []


def test_ready_set_excludes_held_by_other():
    repo = _repo(
        _m(ROOT, "design:ack"),
        _m("KLC-078", "design:ack",
           holder={"id": "alice", "machine": "box", "since": "2026-01-01T00:00:00Z"}),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="bob")
    assert rep.occupied == ["KLC-078"]
    assert "KLC-078" not in rep.ready
    assert ROOT in rep.ready


def test_held_by_self_still_ready():
    repo = _repo(
        _m(ROOT, "design:ack",
           holder={"id": "me", "machine": "box", "since": "2026-01-01T00:00:00Z"}),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert rep.ready == [ROOT]
    assert rep.occupied == []


def test_terminal_member_is_done_not_ready():
    repo = _repo(_m(ROOT, "archived"))
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert rep.ready == []
    assert rep.members[0].status == "done"


# --- MEDIUM-1: cross-epic upstream resolves, is NOT dangling ------------------

def test_cross_epic_upstream_reached_shows_ready():
    # KLC-078 (in ROOT's epic) depends on KLC-500 which belongs to a DIFFERENT
    # epic but exists and has reached `integrated`. The edge must resolve through
    # epic_deps -> KLC-078 READY, with NO false "not a member" dangling warning.
    repo = _repo(
        _m(ROOT, "design:ack"),
        _m("KLC-078", "intake:ack-needed", blocked_by=[
            {"on": "KLC-500", "phase": "build", "point": "integrated"}]),
        _m("KLC-500", "integrate:ack", epic="OTHER-EPIC"),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.ready, rep.blocked
    assert "KLC-078" not in rep.blocked
    assert not any("dangling" in w for w in rep.warnings), rep.warnings
    # membership is still ROOT-only
    assert {m.key for m in rep.members} == {ROOT, "KLC-078"}


def test_cross_epic_upstream_not_reached_blocks():
    # Same shape but the out-of-epic upstream has NOT reached the point -> blocked
    # (resolved, not dangling).
    repo = _repo(
        _m(ROOT, "design:ack"),
        _m("KLC-078", "design:ack", blocked_by=[
            {"on": "KLC-500", "phase": "build", "point": "integrated"}]),
        _m("KLC-500", "design:work", epic="OTHER-EPIC"),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.blocked
    assert not any("dangling" in w for w in rep.warnings), rep.warnings


# --- validation: cycles -------------------------------------------------------

def test_cycle_detection_mutual_edge():
    repo = _repo(
        _m("KLC-A", "intake:ack-needed", epic="KLC-A", blocked_by=[
            {"on": "KLC-B", "phase": "build", "point": "integrated"}]),
        _m("KLC-B", "intake:ack-needed", epic="KLC-A", blocked_by=[
            {"on": "KLC-A", "phase": "build", "point": "integrated"}]),
    )
    rep = epic_view.compute_epic("KLC-A", repo, me="me")
    assert any("cycle" in w for w in rep.warnings), rep.warnings


def test_no_cycle_on_linear_chain():
    repo = _repo(
        _m(ROOT, "design:ack"),
        _m("KLC-078", "intake:ack-needed", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "integrated"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert not any("cycle" in w for w in rep.warnings), rep.warnings


# --- validation: dangling (truly unknown on) ----------------------------------

def test_dangling_unknown_ticket():
    repo = _repo(
        _m(ROOT, "design:ack"),
        _m("KLC-078", "design:ack", blocked_by=[
            {"on": "KLC-999", "phase": "build", "point": "integrated"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert any("dangling" in w and "unknown ticket" in w for w in rep.warnings), \
        rep.warnings
    # a dangling edge gating the immediate next :work is unsatisfiable -> blocked
    assert "KLC-078" in rep.blocked


# --- LOW-2: dead edge (gated phase not in downstream track) -------------------

def test_dead_edge_does_not_block():
    # `detailed-test-plan` is an L-only phase; on an M-track ticket the guard
    # never enters it, so an edge gating it can never fire -> not blocking, warned.
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "intake:ack-needed", track="M", blocked_by=[
            {"on": ROOT, "phase": "detailed-test-plan", "point": "integrated"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" not in rep.blocked
    assert "KLC-078" in rep.ready
    assert any("dead edge" in w for w in rep.warnings), rep.warnings


# --- condition edges (delegated to epic_deps.condition_holds) -----------------

def test_condition_failed_blocks_via_epic_deps():
    repo = _repo(
        _m(ROOT, "integrate:ack",
           phase_history=[{"event": "jump", "note": "reopened"}]),
        _m("KLC-078", "design:ack", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "integrated",
             "condition": "passed"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.blocked
    v = next(m for m in rep.members if m.key == "KLC-078")
    assert any("not satisfied" in e.describe() for e in v.unmet), v.unmet


def test_condition_holds_unblocks_when_clean():
    repo = _repo(
        _m(ROOT, "integrate:ack", phase_history=[{"event": "ack"}]),
        _m("KLC-078", "intake:ack-needed", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "integrated",
             "condition": "passed"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" not in rep.blocked


# --- MEDIUM-3: a corrupt phase_history entry is never fatal -------------------

def test_non_dict_phase_history_entry_not_fatal():
    # A hand-edited upstream with a non-dict phase_history entry must not crash
    # the view; the condition is evaluated over the well-formed entries only.
    repo = _repo(
        _m(ROOT, "integrate:ack",
           phase_history=["oops-not-a-dict", {"event": "ack"}]),
        _m("KLC-078", "intake:ack-needed", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "integrated",
             "condition": "passed"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")  # must not raise
    # clean well-formed history -> condition holds -> not blocked
    assert "KLC-078" not in rep.blocked


def test_epic_deps_condition_holds_skips_non_dict_history():
    # Direct assertion on the shared resolver (benefits enforcement too).
    up = {"track": "M", "phase": "integrate:ack",
          "phase_history": ["junk", 42, {"event": "ack"}]}
    assert epic_deps.condition_holds("passed", up) is True
    tainted = {"track": "M", "phase": "integrate:ack",
               "phase_history": [None, {"event": "jump"}]}
    assert epic_deps.condition_holds("passed", tainted) is False


# --- single-resolver wiring ---------------------------------------------------

def test_delegates_reached_to_epic_deps(monkeypatch):
    # Upstream still in design:work: the real resolver would keep KLC-078
    # blocked. Force epic_deps.reached to True and the member must go ready,
    # proving epic_view routes the milestone decision through epic_deps.
    monkeypatch.setattr(epic_deps, "reached", lambda meta, point: True)
    repo = _repo(
        _m(ROOT, "design:work"),
        _m("KLC-078", "design:ack", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "design-accepted"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.ready
    assert rep.blocked == []


def test_unknown_point_flagged_and_blocks():
    # epic_deps.reached raises ValueError on an unknown point -> flagged + blocked
    # (member at design:ack so `build` is its immediate next :work entry).
    repo = _repo(
        _m(ROOT, "design:ack"),
        _m("KLC-078", "design:ack", blocked_by=[
            {"on": ROOT, "phase": "build", "point": "bogus-point"}]),
    )
    rep = epic_view.compute_epic(ROOT, repo, me="me")
    assert "KLC-078" in rep.blocked
    assert any("unknown point" in w for w in rep.warnings), rep.warnings
