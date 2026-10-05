"""KLC-179 step-2 (AC-4): gates write facts into meta.facts; meta.phase stays the legacy string.

A light ticket is driven through real `can_complete`, `set_state` and `apply_ack` on a tmp
project. Discovery-lite's own gate (spec quality, reviewers) is stubbed because it is heavy and
not what is under test; the staging in `can_complete` around it is real.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills"), str(_FW / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc114_helpers as h  # noqa: E402
import lifecycle  # noqa: E402
import phase_completion  # noqa: E402
import rules  # noqa: E402

KEY = "KLC-T9"
VERIFY = "python3 -m pytest tests/test_a.py -q"
PLAN = (
    "## step-1 — thing\n\n- Goal: g\n- RED: `tests/test_a.py::test_a`\n- GREEN: do it\n"
    f"- VERIFY: `{VERIFY}`\n- COMMIT: `{KEY} step-1: thing`\n- Affected: `src.py`\n"
    "- Interfaces: none\n- Expected: `1 passed`\n- Depends on: none\n\n"
    "```python\n# sketch\npass\n```\n\n"
)


def _ts(delta_s: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _init_repo(repo: Path) -> None:
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["config", "commit.gpgsign", "false"]):
        h._run(["git", *a], repo)
    h.commit(repo, {"tests/test_a.py": "def test_a():\n    assert True\n"},
             f"{KEY} step-1: add failing tests")
    h.commit(repo, {"src.py": "x = 1\n"}, f"{KEY} step-1: thing")


def _green_steps(tdir: Path) -> None:
    repo = tdir.parents[2]
    (tdir / "build").mkdir(exist_ok=True)
    verify = {"command": VERIFY, "exit_code": 0, "summary_line": "1 passed", "ran_at": _ts(60),
              "runner": "agent", "head": h._run(["git", "rev-parse", "HEAD"], repo), "dirty": False}
    (tdir / "build" / "steps.json").write_text(
        json.dumps({"steps": {"1": {"step": 1, "verify": verify}}}), encoding="utf-8")


def _meta(tdir: Path) -> dict:
    return json.loads((tdir / "meta.json").read_text("utf-8"))


def _ticket(tmp_path, monkeypatch, phase: str, track: str = "S", **extra) -> Path:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    tdir = h.make_ticket(tmp_path, KEY, track, PLAN,
                         meta_extra={"phase": phase, "phase_history": [], **extra})
    _init_repo(tmp_path)
    return tdir


def _consistent(tdir: Path, hint: str, tags=None) -> dict:
    meta = _meta(tdir)
    facts = meta["facts"]
    assert meta["phase"] == rules.phase_for(facts, hint, risk_tags=tags), (meta["phase"], facts)
    return facts


def _gate(phase_id: str, hint: str = "ack-needed") -> None:
    ok, msg = phase_completion.can_complete(KEY, phase_id)
    assert ok, msg
    lifecycle.set_state(KEY, phase_id, hint, event="manual-completion")


def test_gates_write_facts_and_derived_phase(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "discovery-lite:work")
    monkeypatch.setattr(phase_completion, "can_complete_discovery_lite", lambda t, persist=True: (True, ""))

    _gate("discovery-lite")
    facts = _consistent(tdir, "ack-needed", [])
    assert "spec_approved" not in facts and facts["plan_reviewed"] is True   # F-002: the human writes it
    assert facts["track"] == "light"
    assert lifecycle.apply_ack(KEY, 1) == "build:work"
    facts = _consistent(tdir, "work", [])
    assert "steps_green" not in facts

    _green_steps(tdir)
    _gate("build")
    assert _consistent(tdir, "ack-needed", [])["steps_green"] is True
    assert lifecycle.apply_ack(KEY, 1) == "review:work"
    _consistent(tdir, "work", [])

    (tdir / "review-report.md").write_text("# Review\n\n## Verdict: APPROVED\n", encoding="utf-8")
    _gate("review")
    assert _consistent(tdir, "ack-needed", [])["review_verdict"] == "APPROVED"
    assert lifecycle.apply_ack(KEY, 1) == "integrate:work"
    _consistent(tdir, "work", [])

    lifecycle.set_state(KEY, "integrate", "ack-needed", event="manual-completion")
    assert "merged" not in _meta(tdir)["facts"]
    _consistent(tdir, "integrate:ack-needed", [])           # F-009
    lifecycle.apply_ack(KEY, None)
    meta = _meta(tdir)
    assert meta["facts"]["merged"] is True
    assert meta["phase"] == "archived" and meta["facts"]["terminal"] == "archived"
    order = [f for f in rules.FACT_ORDER if f in meta["facts"]]
    assert order == ["spec_approved", "plan_reviewed", "steps_green", "review_verdict", "merged"]
    assert meta["phase_history"][-1]["phase"] == "archived"


def test_failing_gate_writes_no_fact(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "build:work",
                   facts={"track": "light", "spec_approved": True, "plan_reviewed": True})
    # no build/steps.json: the real build gate refuses
    ok, _msg = phase_completion.can_complete(KEY, "build")
    assert not ok
    assert "facts" not in lifecycle._meta_patches.get(KEY, {})
    lifecycle.set_state(KEY, "build", "work", event="set_state")
    assert "steps_green" not in _meta(tdir)["facts"]


def test_read_only_probe_stages_nothing(tmp_path, monkeypatch):
    _ticket(tmp_path, monkeypatch, "build:work")
    _green_steps(tmp_path / ".klc" / "tickets" / KEY)
    ok, msg = phase_completion.can_complete(KEY, "build", persist=False)
    assert ok, msg
    assert KEY not in lifecycle._meta_patches or "facts" not in lifecycle._meta_patches[KEY]


def test_review_changes_requested_verdict_is_written_from_the_report(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "review:work",
                   facts={"track": "light", "spec_approved": True, "plan_reviewed": True,
                          "steps_green": True})
    (tdir / "review-report.md").write_text("## Verdict: CHANGES_REQUESTED\n", encoding="utf-8")
    _gate("review")
    facts = _consistent(tdir, "ack-needed", [])
    assert facts["review_verdict"] == "CHANGES_REQUESTED"
    assert lifecycle.apply_ack(KEY, 2) == "build:work"          # request-changes
    facts = _consistent(tdir, "work", [])
    assert "steps_green" not in facts and "review_verdict" not in facts
    assert facts["spec_approved"] is True and facts["plan_reviewed"] is True


def test_manual_ack_writes_manual_passed_and_failed_clears(tmp_path, monkeypatch):
    all_true = {n: True for n in ("spec_approved", "test_plan_approved", "design_approved",
                                  "plan_reviewed", "steps_green")}
    all_true.update(review_verdict="APPROVED", track="full")
    tdir = _ticket(tmp_path, monkeypatch, "manual:ack-needed", track="M",
                   risk_tags=["user-facing"], facts=dict(all_true))
    assert lifecycle.apply_ack(KEY, 1, "walked it") == "integrate:work"
    facts = _meta(tdir)["facts"]
    assert facts["manual_passed"] is True
    assert rules.next_move(facts, "M", risk_tags=["user-facing"]).action == "integrate"

    tdir2 = tdir
    lifecycle.write_meta(KEY, {**_meta(tdir2), "phase": "manual:ack-needed",
                               "facts": {**all_true, "manual_passed": True}})
    assert lifecycle.apply_ack(KEY, 2) == "build:work"          # failed
    facts = _meta(tdir2)["facts"]
    assert "steps_green" not in facts and "manual_passed" not in facts
    assert facts["design_approved"] is True


def test_back_clears_target_fact_and_every_later_one(tmp_path, monkeypatch):
    all_true = {n: True for n in ("spec_approved", "plan_reviewed", "steps_green", "merged")}
    all_true.update(review_verdict="APPROVED", track="light")
    tdir = _ticket(tmp_path, monkeypatch, "integrate:ack", facts=all_true)
    lifecycle.jump(KEY, "build")
    facts = _meta(tdir)["facts"]
    assert set(facts) - {"retro_required"} == {"spec_approved", "plan_reviewed", "track"}
    assert facts["retro_required"] is True       # the jump counts as rework (today's detection)
    assert _consistent(tdir, "work", [])


def test_in_flight_ticket_without_facts_is_derived_then_written_once(tmp_path, monkeypatch):
    history = [{"phase": "discovery-lite:ack", "event": "ack", "started_at": _ts(-60),
                "pick": {"id": 1, "label": "approve"}},
               {"phase": "build:work", "event": "advance", "started_at": _ts(-30)}]
    tdir = _ticket(tmp_path, monkeypatch, "build:work", phase_history=history)
    assert "facts" not in _meta(tdir)
    _green_steps(tdir)
    _gate("build")
    facts = _meta(tdir)["facts"]
    assert facts["spec_approved"] is True and facts["plan_reviewed"] is True
    assert facts["steps_green"] is True and facts["track"] == "light"


def test_track_fact_follows_meta_track_on_every_write(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "design:work", track="M")
    lifecycle.set_state(KEY, "design", "work", event="set_state")
    assert _meta(tdir)["facts"]["track"] == "full"


@pytest.mark.parametrize("facts,hint,tags,expected", [
    ({"track": "light"}, "work", None, "discovery-lite:work"),
    ({"track": "full"}, "work", None, "discovery:work"),
    ({"track": "light", "spec_approved": True, "plan_reviewed": True}, "ack-needed", None,
     "discovery-lite:ack-needed"),
    ({"track": "light", "spec_approved": True, "plan_reviewed": True}, "work", None, "build:work"),
    ({"track": "full", "spec_approved": True, "test_plan_approved": True, "design_approved": True,
      "plan_reviewed": True}, "ack", None, "design:ack"),
    ({"track": "full", "spec_approved": True, "test_plan_approved": True, "design_approved": True,
      "plan_reviewed": True, "steps_green": True, "review_verdict": "CHANGES_REQUESTED"},
     "ack-needed", None, "review:ack-needed"),
    ({"track": "full", "spec_approved": True, "test_plan_approved": True, "design_approved": True,
      "plan_reviewed": True, "steps_green": True, "review_verdict": "APPROVED"},
     "work", ["data"], "manual:work"),
    ({"track": "light", "terminal": "archived"}, "work", None, "archived"),
    ({"track": "light", "terminal": "cancelled"}, "ack", None, "cancelled"),
])
def test_phase_for(facts, hint, tags, expected):
    assert rules.phase_for(facts, hint, risk_tags=tags) == expected


def test_fix_track_mirrors_the_lane_into_facts(tmp_path):
    import os
    import subprocess
    td = tmp_path / ".klc" / "tickets" / "KLC-T8"
    td.mkdir(parents=True)
    (td / "meta.json").write_text(json.dumps({
        "ticket": "KLC-T8", "kind": "tech", "phase": "build:work", "track": "M",
        "phase_history": [], "affected_modules": ["a"], "created": "2026-01-01T00:00:00Z"}),
        encoding="utf-8")
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    p = subprocess.run([sys.executable, str(_FW / "scripts" / "klc"), "fix", "KLC-T8", "track", "S",
                        "--reason", "small"], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    meta = json.loads((td / "meta.json").read_text("utf-8"))
    assert meta["track"] == "S" and meta["facts"]["track"] == "light"
