"""KLC-179 step-3 (AC-2): switching the lane keeps the ticket alive.

`lifecycle.switch_track` rewrites `facts.track` and the legacy letter, keeps every fact it
already has, and lands on the first missing fact of the new lane. It never archives
(the KLC-163 bug: a retrack on an early phase walked a ticket straight to `archived`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills"), str(_FW / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc114_helpers as h  # noqa: E402
import lifecycle  # noqa: E402
import rules  # noqa: E402

KEY = "KLC-T9"


def _ticket(tmp_path, monkeypatch, phase: str, track: str, facts: dict | None = None, **extra):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    meta_extra = {"phase": phase, "phase_history": [], **extra}
    if facts is not None:
        meta_extra["facts"] = facts
    return h.make_ticket(tmp_path, KEY, track, "## step-1 — x\n", meta_extra=meta_extra)


def _meta(tdir: Path) -> dict:
    return json.loads((tdir / "meta.json").read_text("utf-8"))


def test_switch_never_archives(tmp_path, monkeypatch):
    # light at build -> full: the test plan and the design are still missing
    tdir = _ticket(tmp_path, monkeypatch, "build:work", "S",
                   {"track": "light", "spec_approved": True, "plan_reviewed": True})
    assert lifecycle.switch_track(KEY, "full") == "acceptance-test-plan:work"
    meta = _meta(tdir)
    assert meta["facts"]["track"] == "full" and meta["track"] == "M"       # letter mirror
    assert meta["facts"]["spec_approved"] is True and meta["facts"]["plan_reviewed"] is True
    assert meta["phase"] != "archived"
    assert meta["phase_history"][-1]["event"] == "track-switch"

    # full at review -> light: the facts it has stay, the next move is review
    tdir = _ticket(tmp_path, monkeypatch, "review:work", "L",
                   {"track": "full", "spec_approved": True, "test_plan_approved": True,
                    "design_approved": True, "plan_reviewed": True, "steps_green": True})
    assert lifecycle.switch_track(KEY, "light") == "review:work"
    meta = _meta(tdir)
    assert meta["track"] == "S" and meta["facts"]["track"] == "light"
    assert meta["facts"]["design_approved"] is True and meta["facts"]["steps_green"] is True

    # the KLC-163 case: light at discovery, nothing established yet
    tdir = _ticket(tmp_path, monkeypatch, "discovery-lite:work", "S", {"track": "light"})
    assert lifecycle.switch_track(KEY, "full") == "discovery:work"
    assert _meta(tdir)["phase"] == "discovery:work"


def test_switch_keeps_facts_across_the_following_moves(tmp_path, monkeypatch):
    """Entering a later phase after a switch must not wipe the facts the ticket kept.
    (F-012: a light -> full switch with no design clears the build and the verdict, because
    the design will change the plan; the other facts stay.)"""
    tdir = _ticket(tmp_path, monkeypatch, "review:ack-needed", "S",
                   {"track": "light", "spec_approved": True, "plan_reviewed": True,
                    "steps_green": True})
    lifecycle.switch_track(KEY, "full")
    assert _meta(tdir)["phase"] == "acceptance-test-plan:work"
    lifecycle.set_state(KEY, "acceptance-test-plan", "ack-needed", event="manual-completion")
    assert lifecycle.apply_ack(KEY, 1) == "design:work"
    facts = _meta(tdir)["facts"]
    assert facts["test_plan_approved"] is True and facts["spec_approved"] is True
    assert "steps_green" not in facts


def test_switch_with_all_gate_facts_but_merged_lands_on_integrate_not_archive(tmp_path, monkeypatch):
    facts = {n: True for n in ("spec_approved", "plan_reviewed", "steps_green")}
    facts.update(review_verdict="APPROVED", track="light")
    tdir = _ticket(tmp_path, monkeypatch, "integrate:work", "S", facts)
    lifecycle.switch_track(KEY, "light")
    assert _meta(tdir)["phase"] == "integrate:work"
    full = _ticket(tmp_path, monkeypatch, "integrate:work", "S", dict(facts))
    assert lifecycle.switch_track(KEY, "full") == "acceptance-test-plan:work"
    assert _meta(full)["phase"] != "archived"


def test_switch_refuses_terminal_and_unknown_lane(tmp_path, monkeypatch):
    _ticket(tmp_path, monkeypatch, "archived", "S", {"track": "light", "terminal": "archived"})
    with pytest.raises(ValueError):
        lifecycle.switch_track(KEY, "full")
    _ticket(tmp_path, monkeypatch, "build:work", "S", {"track": "light"})
    with pytest.raises(ValueError):
        lifecycle.switch_track(KEY, "turbo")


def test_switch_reads_a_legacy_ticket_without_facts(tmp_path, monkeypatch):
    history = [{"phase": "discovery-lite:ack", "event": "ack", "started_at": "2026-01-01T00:00:00Z",
                "pick": {"id": 1, "label": "approve"}}]
    tdir = _ticket(tmp_path, monkeypatch, "build:work", "S", phase_history=history)
    assert "facts" not in _meta(tdir)
    assert lifecycle.switch_track(KEY, "full") == "acceptance-test-plan:work"
    assert _meta(tdir)["facts"]["spec_approved"] is True


def test_fix_track_calls_switch_track_and_keeps_the_letter(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(_FW / "core" / "phases"))
    import fix
    tdir = _ticket(tmp_path, monkeypatch, "discovery-lite:work", "S", {"track": "light"})
    rc = fix.run([KEY, "track", "L", "--reason", "bigger than it looked"])
    assert rc == 0, capsys.readouterr()
    meta = _meta(tdir)
    assert meta["track"] == "L" and meta["facts"]["track"] == "full"
    assert meta["phase"] == "discovery:work"                    # never archived
    assert any(e.get("event") == "retrack" for e in meta["phase_history"])
