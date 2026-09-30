#!/usr/bin/env python3
"""tests/integration/test_klc127_handback_planning.py — KLC-127 step-3, AC-8:
`handback.py take` runs the review planner (`scripts/review.py --plan-only`)
before recording a review-kind pass when the ticket has no review-plan.json,
and degrades to one note (still exit 0) when planning itself fails or the
plan marks the pass skipped.

Hermetic: PROJECT_ROOT points at a tmp project; `subprocess.run` is
monkeypatched in the one test that inspects the real `_run_planner`'s argv,
so no test here launches a subprocess or runs git for real.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import handback  # noqa: E402
import metrics  # noqa: E402
import review_plan  # noqa: E402

TICKET = "KLC-991"


def _seed_ticket(tmp_path: Path, *, track: str = "M") -> tuple[Path, Path]:
    project_root = tmp_path / "proj"
    tdir = project_root / ".klc" / "tickets" / TICKET
    tdir.mkdir(parents=True)
    meta = {
        "ticket": TICKET, "kind": "tech", "kind_source": "user",
        "phase": "build:work", "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "spec.md").write_text("spec\n", encoding="utf-8")
    return project_root, tdir


@pytest.fixture()
def project(tmp_path, monkeypatch):
    project_root, tdir = _seed_ticket(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    return project_root, tdir


def _verdict(findings=None) -> dict:
    return {"findings": [] if findings is None else findings, "decisions_to_confirm": []}


def _finding(**overrides) -> dict:
    d = {"id": "F-1", "rule_name": "readability", "severity": "HIGH", "file": "f.py",
         "line": 5, "title": "a title", "body": "a body", "fix": None}
    d.update(overrides)
    return d


def _tagged_attempts(tdir: Path) -> list[dict]:
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    return [rec for _phase, rec in metrics.iter_attempts(meta, TICKET) if rec.get("reviewer")]


def test_take_runs_the_planner_when_no_review_plan_exists(project, tmp_path, monkeypatch):
    """AC-8: no review-plan.json exists — the planner runs first, writes a
    real plan, and the pass is then recorded."""
    project_root, tdir = project

    def _stub_planner(ticket):
        plan = review_plan.build_plan(
            ticket=ticket, track="M", path="job", diff_sha256="abc123", cap=None,
            override=False,
            passes=[review_plan.pass_entry("code-review", "manifest-always", "auto",
                                           None, None, "planned")])
        review_plan.write_plan(ticket, plan)
        return True

    monkeypatch.setattr(handback, "_run_planner", _stub_planner)
    assert not (tdir / "review-plan.json").exists()

    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps(_verdict(findings=[_finding()])), encoding="utf-8")
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 0

    stored_plan = json.loads((tdir / "review-plan.json").read_text(encoding="utf-8"))
    entry = next(p for p in stored_plan["passes"] if p["reviewer"] == "code-review")
    assert entry["status"] == "executed"
    assert len(_tagged_attempts(tdir)) == 1


@pytest.mark.parametrize("failure", ["returns-false", "raises-timeout"])
def test_take_degrades_to_one_note_and_exit_0_when_planning_fails(
        project, tmp_path, monkeypatch, failure, capsys):
    """AC-8: the planner failing (returns False, or raises a subprocess
    timeout) degrades to one note; the hand-back is still accepted (exit 0)."""
    _project_root, tdir = project

    if failure == "returns-false":
        monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)
    else:
        def _boom(ticket):
            raise subprocess.TimeoutExpired(cmd=["review.py"], timeout=120)
        monkeypatch.setattr(handback, "_run_planner", _boom)

    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps(_verdict(findings=[_finding()])), encoding="utf-8")
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 0
    assert not (tdir / "review-plan.json").exists()
    assert _tagged_attempts(tdir) == []
    out = capsys.readouterr().out
    assert "note" in out


def test_take_degrades_to_one_note_and_exit_0_when_the_plan_marks_the_pass_skipped(
        project, tmp_path, monkeypatch, capsys):
    """AC-8: an existing plan that marks the pass `skipped` degrades to one
    note; the hand-back is still accepted."""
    _project_root, tdir = project
    plan = review_plan.build_plan(
        ticket=TICKET, track="S", path="job", diff_sha256="abc123", cap=None,
        override=False,
        passes=[review_plan.pass_entry("code-review", "manifest-conditional", "auto",
                                       None, None, "skipped", skip_reason="cascade: no signal")])
    review_plan.write_plan(TICKET, plan)
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)

    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps(_verdict(findings=[_finding()])), encoding="utf-8")
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 0
    assert _tagged_attempts(tdir) == []
    stored_plan = json.loads((tdir / "review-plan.json").read_text(encoding="utf-8"))
    entry = next(p for p in stored_plan["passes"] if p["reviewer"] == "code-review")
    assert entry["status"] == "skipped"
    out = capsys.readouterr().out
    assert "note" in out


def test_take_notes_when_the_pass_is_not_in_the_plan(project, tmp_path, monkeypatch, capsys):
    """AC-8: an existing plan that never lists the pass degrades to one note."""
    _project_root, tdir = project
    plan = review_plan.build_plan(
        ticket=TICKET, track="M", path="job", diff_sha256="abc123", cap=None,
        override=False,
        passes=[review_plan.pass_entry("deep-impact", "manifest-always", "auto",
                                       None, None, "planned")])
    review_plan.write_plan(TICKET, plan)
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)

    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps(_verdict(findings=[_finding()])), encoding="utf-8")
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 0
    assert _tagged_attempts(tdir) == []
    out = capsys.readouterr().out
    assert "note" in out


def test_planner_command_names_plan_only_the_main_diff_range_and_the_ticket_spec(
        project, monkeypatch):
    """AC-8: the real `_run_planner` invokes `scripts/review.py --plan-only
    --diff main...HEAD --spec <ticket>/spec.md`."""
    project_root, tdir = project
    calls = []

    class _FakeCompleted:
        returncode = 0

    def _fake_run(argv, cwd=None, capture_output=None, text=None, timeout=None):
        calls.append((argv, cwd, timeout))
        return _FakeCompleted()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    result = handback._run_planner(TICKET)
    assert result is True
    assert len(calls) == 1
    argv, cwd, timeout = calls[0]
    assert argv[0] == sys.executable
    assert argv[1].endswith("review.py")
    assert "--plan-only" in argv
    assert argv[argv.index("--diff") + 1] == "main...HEAD"
    assert argv[argv.index("--spec") + 1] == str(tdir / "spec.md")
    assert cwd == str(project_root)
    assert timeout == 120
