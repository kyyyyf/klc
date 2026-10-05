"""KLC-173 step-3 (AC-7): one review/review-plan-r<N>.json per diff; take re-plans
when the diff changed and counts each round's pass once."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import handback  # noqa: E402
import metrics  # noqa: E402
import review_plan  # noqa: E402

TICKET = "KLC-991"


@pytest.fixture()
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    tdir = root / ".klc" / "tickets" / TICKET
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(json.dumps(
        {"ticket": TICKET, "kind": "tech", "phase": "build:work", "phase_history": [],
         "track": "M"}), "utf-8")
    (tdir / "spec.md").write_text("spec\n", "utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    return tdir


def _plan(sha, status="planned"):
    return review_plan.build_plan(
        ticket=TICKET, track="M", path="job", diff_sha256=sha, cap=None, override=False,
        passes=[review_plan.pass_entry("code-review", "manifest-always", "auto",
                                       None, None, status)])


def _verdict(tmp_path, title):
    f = {"id": "F-1", "rule_name": "readability", "severity": "HIGH", "file": "f.py",
         "line": 5, "title": title, "body": "b", "fix": None}
    p = tmp_path / f"v-{title}.json"
    p.write_text(json.dumps({"findings": [f], "decisions_to_confirm": []}), "utf-8")
    return p


def _attempts(tdir):
    meta = json.loads((tdir / "meta.json").read_text("utf-8"))
    return [r for _p, r in metrics.iter_attempts(meta, TICKET) if r.get("reviewer")]


def test_write_plan_picks_the_round_by_diff_sha(project):
    tdir = project
    p1 = review_plan.write_plan(TICKET, _plan("A" * 64))
    assert p1 == tdir / "review" / "review-plan-r1.json"
    assert json.loads(p1.read_text("utf-8"))["round"] == 1
    again = review_plan.write_plan(TICKET, _plan("A" * 64))        # same diff: same round
    assert again == p1
    p2 = review_plan.write_plan(TICKET, _plan("B" * 64))           # new diff: next round
    assert p2 == tdir / "review" / "review-plan-r2.json"
    assert review_plan.latest_plan_path(TICKET) == p2
    assert review_plan.round_of(p2) == 2 and review_plan.round_of(p1) == 1
    assert not (tdir / "review-plan.json").exists()


def test_legacy_root_plan_reads_as_round_one(project):
    tdir = project
    (tdir / "review-plan.json").write_text(json.dumps(_plan("A" * 64)), "utf-8")
    legacy = tdir / "review-plan.json"
    assert review_plan.latest_plan_path(TICKET) == legacy
    assert review_plan.round_of(legacy) == 1
    assert review_plan.write_plan(TICKET, _plan("B" * 64)) == tdir / "review" / "review-plan-r2.json"


def test_new_diff_makes_round_two_plan_and_counts_once(project, tmp_path, monkeypatch):
    tdir = project
    sha = {"v": "A" * 64}
    monkeypatch.setattr(handback, "_current_diff_sha", lambda t: sha["v"])

    def planner(ticket):
        review_plan.write_plan(ticket, _plan(sha["v"]))
        return handback.PlannerResult(True)

    monkeypatch.setattr(handback, "_run_planner", planner)
    take = lambda title: handback.take("code-review", TICKET, _verdict(tmp_path, title))  # noqa: E731
    assert take("r1") == 0
    assert len(_attempts(tdir)) == 0          # KLC-174: no `estimated` attempt
    assert take("r1-again") == 0                                   # same diff: not counted twice
    assert len(_attempts(tdir)) == 0
    sha["v"] = "B" * 64                                            # the diff changed
    assert take("r2") == 0
    assert len(_attempts(tdir)) == 0
    assert take("r2-again") == 0
    assert len(_attempts(tdir)) == 0
    r1 = json.loads((tdir / "review" / "review-plan-r1.json").read_text("utf-8"))
    r2 = json.loads((tdir / "review" / "review-plan-r2.json").read_text("utf-8"))
    assert r1["diff_sha256"] == "A" * 64 and r2["diff_sha256"] == "B" * 64
    assert r1["passes"][0]["status"] == "executed" and r2["passes"][0]["status"] == "executed"
    assert not (tdir / "review-plan-r3.json").exists()
    assert not list((tdir / "review").glob("review-plan-r3.json"))
    import findings_store as fs
    got = fs.read(tdir, kind="code-review")[0]
    assert sorted((f.round, f.title) for f in got) == [(1, "r1-again"), (2, "r2-again")]


def test_take_keeps_a_stale_plan_when_the_diff_cannot_be_had(project, tmp_path, monkeypatch):
    tdir = project
    review_plan.write_plan(TICKET, _plan("A" * 64))
    monkeypatch.setattr(handback, "_current_diff_sha", lambda t: None)
    calls = []
    monkeypatch.setattr(handback, "_run_planner",
                        lambda t: calls.append(t) or handback.PlannerResult(False, "x"))
    assert handback.take("code-review", TICKET, _verdict(tmp_path, "x")) == 0
    assert calls == [] and len(_attempts(tdir)) == 0
