#!/usr/bin/env python3
"""tests/integration/test_klc127_handback_planning.py — KLC-127 step-3, AC-8:
`handback.py take` runs the review planner (`scripts/review.py --plan-only`)
before recording a review-kind pass when the ticket has no review-plan.json,
and degrades to one note (still exit 0) when planning itself fails or the
plan marks the pass skipped.

Hermetic: PROJECT_ROOT points at a tmp project. KLC-166 step-2 (AC-9): the
four `_run_planner` stubs below now return `handback.PlannerResult`, not a
bare bool (D-003 keeps a bare bool working too, for the OTHER hand-back
suites that are not touched by this ticket). The argv test fakes
`subprocess.run` for every call it sees (the real range resolution now
makes `git` calls too) and writes a real plan, so — unlike the claim this
docstring used to make — that one test DOES exercise a faked subprocess and
git call path; the real subprocess/real-git coverage itself lives in this
module's siblings (`tests/integration/test_klc166_planner_range.py`,
`tests/integration/test_klc166_planner_tempfile_cleanup.py`,
`tests/e2e/test_klc166_handback_take_e2e.py`, AC-7/AC-8).
"""
from __future__ import annotations

import hashlib
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
        return handback.PlannerResult(True)

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
        monkeypatch.setattr(handback, "_run_planner",
                            lambda ticket: handback.PlannerResult(False, "stub"))
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
    monkeypatch.setattr(handback, "_run_planner",
                        lambda ticket: handback.PlannerResult(False, "stub"))

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
    monkeypatch.setattr(handback, "_run_planner",
                        lambda ticket: handback.PlannerResult(False, "stub"))

    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps(_verdict(findings=[_finding()])), encoding="utf-8")
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 0
    assert _tagged_attempts(tdir) == []
    out = capsys.readouterr().out
    assert "note" in out


def test_planner_command_names_plan_only_a_real_diff_file_and_the_ticket_spec(
        project, monkeypatch):
    """AC-9 (KLC-166 step-2): the real `_run_planner` now resolves the
    ticket's range through `phase_completion.ticket_diff_range` (real `git`
    calls) and invokes `scripts/review.py --plan-only --diff <a file that
    existed during the call>` — never the literal `main...HEAD` the
    original bug passed. The fake `subprocess.run` answers every `git` call
    `ticket_diff_range`/the materialising diff make with real-shaped
    `CompletedProcess` values, and for the `review.py` call writes a real
    `review_plan.build_plan` plan carrying that file's SHA-256 (C-004:
    never fabricate a shape the real writer would never produce)."""
    project_root, tdir = project
    calls = []
    live_base = "a" * 40
    live_head = "b" * 40
    diff_bytes = b"diff --git a/widgets/thing.py b/widgets/thing.py\n+a = 1\n"

    def _fake_run(argv, cwd=None, capture_output=None, text=None, timeout=None, errors=None):
        calls.append((list(argv), cwd, timeout))
        if argv[0] == "git":
            if argv[1:4] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return subprocess.CompletedProcess(argv, 0, stdout="feature/klc-991-x\n", stderr="")
            if argv[1] == "merge-base":
                return subprocess.CompletedProcess(argv, 0, stdout=live_base + "\n", stderr="")
            if argv[1:3] == ["rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(argv, 0, stdout=live_head + "\n", stderr="")
            if argv[1:3] == ["diff", "--name-only"]:
                return subprocess.CompletedProcess(argv, 0, stdout="widgets/thing.py\n", stderr="")
            if argv[1] == "diff":
                return subprocess.CompletedProcess(argv, 0, stdout=diff_bytes, stderr=b"")
            raise AssertionError(f"unexpected git call: {argv}")
        # the review.py call
        diff_file = Path(argv[argv.index("--diff") + 1])
        assert diff_file.is_file(), "the --diff file must exist during the call"
        sha = hashlib.sha256(diff_file.read_bytes()).hexdigest()
        plan = review_plan.build_plan(
            ticket=TICKET, track="M", path="job", diff_sha256=sha, cap=None,
            override=False,
            passes=[review_plan.pass_entry("code-review", "manifest-always", "auto",
                                           None, None, "planned")])
        review_plan.write_plan(TICKET, plan)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(handback, "_clock", lambda: 1000.0)
    result = handback._run_planner(TICKET)
    assert result, getattr(result, "reason", "")

    review_calls = [c for c in calls if c[0][0] == sys.executable]
    assert len(review_calls) == 1
    argv, cwd, timeout = review_calls[0]
    assert argv[1].endswith("review.py")
    assert "--plan-only" in argv
    diff_arg = Path(argv[argv.index("--diff") + 1])
    assert diff_arg.name != "main...HEAD"
    assert argv[argv.index("--spec") + 1] == str(tdir / "spec.md")
    assert cwd == str(project_root)
    assert timeout == 120
