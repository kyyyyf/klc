"""KLC-179 step-3 (AC-5, AC-9): the rule table drives `go`; a human pick is needed at
`spec_approved` (both lanes), `design_approved` and `manual_passed` when it runs (full). Every
other ack is conditional. `integrate` is conditional too, but its gate checks the merge: a ticket
whose recorded range head is on main passes without a pick, and only a ticket whose merge cannot
be verified asks for `--pick 1` (round-1 F-003, round-2 R2-002, amended AC-5).

The tickets are driven through the real `next_move.compute`, `lifecycle.apply_ack` and
`lifecycle.advance_to_next`; only the gate signals are faked clean (they need git, the
index and review artefacts that are not what is under test).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills"), str(_FW / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gate_policy  # noqa: E402
import klc114_helpers as h  # noqa: E402
import lifecycle  # noqa: E402
import next_move  # noqa: E402
import rules  # noqa: E402

KEY = "KLC-T9"
CLEAN = {"advisory": {"records": [], "threshold": "medium"}, "scope_expansion": False,
         "sentinels": False, "mutation": False, "budget_overrun": False,
         "verdict": "APPROVED", "route_confidence": "high"}


def _git(cwd, *args) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _merged_range(root: Path) -> dict:
    """A scratch repo where a branch commit is merged into main; returns the range whose head
    is therefore an ancestor of main (what a merged ticket records at build/review)."""
    if not (root / ".git").exists():
        _git(root, "init", "-q", "-b", "main")
        for a in (("config", "user.email", "t@t"), ("config", "user.name", "t"),
                  ("config", "commit.gpgsign", "false")):
            _git(root, *a)
        (root / "a.txt").write_text("a\n")
        _git(root, "add", "a.txt")
        _git(root, "commit", "-q", "-m", "init")
    base = _git(root, "rev-parse", "main")
    branch = f"feature/work-{len(_git(root, 'branch', '--list').splitlines())}"
    _git(root, "checkout", "-q", "-b", branch)
    (root / f"{branch.rsplit('/', 1)[1]}.txt").write_text("w\n")
    _git(root, "add", "-A", "--", ".")
    _git(root, "commit", "-q", "-m", "work")
    head = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "main")
    _git(root, "merge", "-q", "--no-ff", "-m", "merge", branch)
    return {"base": base, "head": head, "recorded_at_phase": "review",
            "recorded_at": "2026-01-01T00:00:00Z"}


def _ticket(tmp_path, monkeypatch, track: str, merged: bool = True, **extra) -> Path:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate_policy, "collect_signals", lambda ticket, phase_id: dict(CLEAN))
    if merged:
        extra["pre_merge_range"] = _merged_range(tmp_path)
    else:
        _merged_range(tmp_path)          # a repo exists, the ticket just records no range
    return h.make_ticket(tmp_path, KEY, track, "## step-1 — x\n",
                         meta_extra={"phase": "intake:ack-needed", "phase_history": [],
                                     "route_confidence": "high", **extra})


def _meta(tdir: Path) -> dict:
    return json.loads((tdir / "meta.json").read_text("utf-8"))


def _drive(tdir: Path) -> tuple[list[str], list[str]]:
    """Run the ticket to the end. Returns (phases that asked for a pick, phases visited)."""
    stops: list[str] = []
    visited: list[str] = []
    for _ in range(60):
        phase = _meta(tdir)["phase"]
        if phase in ("archived", "cancelled"):
            return stops, visited
        pid, state = phase.split(":")
        if state == "work":
            visited.append(pid)
            lifecycle.set_state(KEY, pid, "ack-needed", event="manual-completion")
            continue
        move = next_move.compute(KEY)
        if move.action == "next":
            lifecycle.advance_to_next(KEY)
        elif move.action == "ack":
            lifecycle.apply_ack(KEY, move.forward_pick)
        else:
            assert move.action == "pick", move
            stops.append(pid)
            lifecycle.apply_ack(KEY, move.forward_pick)
    raise AssertionError(f"ticket did not finish: {_meta(tdir)['phase']}")


def test_only_decision_points_require_pick(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "S", facts={"track": "light"})
    stops, visited = _drive(tdir)
    assert stops == ["discovery-lite"]
    assert visited == ["discovery-lite", "build", "review", "integrate"]
    assert _meta(tdir)["facts"]["terminal"] == "archived"

    tdir = _ticket(tmp_path, monkeypatch, "L", facts={"track": "full"})
    stops, visited = _drive(tdir)
    assert stops == ["discovery", "design"]
    assert visited == ["discovery", "acceptance-test-plan", "design", "build", "review",
                       "integrate", "learn"]


def test_integrate_asks_for_a_pick_only_when_the_merge_cannot_be_verified(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "S", merged=False, facts={"track": "light"})
    stops, _visited = _drive(tdir)
    assert stops == ["discovery-lite", "integrate"]
    assert _meta(tdir)["integrate"]["confirmed_by_pick"] is True


def test_manual_and_observe_run_on_full_only_when_risk_tags_demand(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "M", facts={"track": "full"}, risk_tags=["security"])
    stops, visited = _drive(tdir)
    assert stops == ["discovery", "design", "manual"]
    assert visited == ["discovery", "acceptance-test-plan", "design", "build", "review",
                       "manual", "integrate", "observe", "learn"]


def test_light_ticket_with_risk_tags_has_no_manual_and_no_observe(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "S", facts={"track": "light"}, risk_tags=["security"])
    stops, visited = _drive(tdir)
    assert stops == ["discovery-lite"]
    assert "manual" not in visited and "observe" not in visited


def test_a_missing_gate_fact_never_lands_on_archived(tmp_path, monkeypatch):
    """Negative: acking integrate on a ticket whose review never ran must not archive."""
    tdir = _ticket(tmp_path, monkeypatch, "S", facts={"track": "light", "spec_approved": True,
                                                      "plan_reviewed": True, "steps_green": True})
    lifecycle.set_state(KEY, "integrate", "ack-needed", event="manual-completion")
    new = lifecycle.apply_ack(KEY, 1)
    assert new != "archived" and new == "review:work", new
    assert _meta(tdir)["facts"]["merged"] is True


def test_rework_pick_clears_downstream_facts_and_returns_to_build(tmp_path, monkeypatch):
    facts = {n: True for n in ("spec_approved", "plan_reviewed", "steps_green")}
    facts.update(review_verdict="CHANGES_REQUESTED", track="light")
    tdir = _ticket(tmp_path, monkeypatch, "S", facts=facts)
    lifecycle.set_state(KEY, "review", "ack-needed", event="manual-completion")
    assert lifecycle.apply_ack(KEY, 2) == "build:work"                       # request-changes
    got = _meta(tdir)["facts"]
    assert "steps_green" not in got and "review_verdict" not in got
    assert got["spec_approved"] is True and got["plan_reviewed"] is True


def test_back_to_build_clears_facts_and_supersedes_the_review_report(tmp_path, monkeypatch):
    facts = {n: True for n in ("spec_approved", "plan_reviewed", "steps_green", "merged")}
    facts.update(review_verdict="APPROVED", track="light")
    tdir = _ticket(tmp_path, monkeypatch, "S", facts=facts)
    lifecycle.write_meta(KEY, {**_meta(tdir), "phase": "integrate:work"})
    (tdir / "review-report.md").write_text("## Verdict: APPROVED\n", encoding="utf-8")
    plan = lifecycle.jump(KEY, "build", from_any=True)
    assert plan["to"] == "build:work"
    assert "review" in plan["supersede"] and "integrate" in plan["supersede"]
    got = _meta(tdir)["facts"]
    assert "steps_green" not in got and "review_verdict" not in got and "merged" not in got
    assert got["spec_approved"] is True
    assert rules.next_move(got, "light").action == "build"
    assert not (tdir / "review-report.md").exists()


def test_xs_ticket_in_flight_is_read_through_derivation(tmp_path, monkeypatch):
    """An XS ticket at the retired `xs-build` / `review-lite` phase still moves on."""
    tdir = _ticket(tmp_path, monkeypatch, "XS")
    lifecycle.write_meta(KEY, {**_meta(tdir), "phase": "xs-build:ack-needed",
                               "phase_history": [{"phase": "xs-build:work", "event": "advance",
                                                  "started_at": "2026-01-01T00:00:00Z"}]})
    assert lifecycle.read_meta(KEY)["phase"] == "build:ack-needed"
    assert lifecycle.apply_ack(KEY, 1) == "review:work"
    lifecycle.write_meta(KEY, {**_meta(tdir), "phase": "review-lite:ack-needed"})
    assert lifecycle.apply_ack(KEY, 1) == "integrate:work"
