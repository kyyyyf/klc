"""KLC-166 step-3 — AC-4/AC-8: the full decision table for `review.py`'s
exit code paired with the written plan's post-condition. `exit 2` means
BOTH "refused before planning" and "over the cap, plan already written" —
only the plan itself (its existence and its `diff_sha256`) tells them
apart (D-005); exit codes other than {0, 2}, and an unreadable plan, are
always a failure even when a matching-looking plan sits on disk.

Every fake here passes every `git` call through to a REAL temporary
repository (D-008) and fakes only the `review.py` argv — never a canned
git answer, per C-004 ("mock the real contract")."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "tests" / "integration"))

import handback  # noqa: E402
import review_plan  # noqa: E402

from _klc128_fixtures import _bare_and_clone, _branch_with_commits, _seed_ticket  # noqa: E402

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def _seed_with_live_range(tmp_path: Path, ticket: str) -> Path:
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch=f"feature/{ticket.lower()}-add-a-widget")
    tdir = _seed_ticket(clone, ticket, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    return clone


def _a_real_m_track_plan(ticket: str, diff_file: Path) -> dict:
    """A real-shape M-track plan at the M cap of 4 (code-review, drift,
    deep-impact, external all planned) carrying *diff_file*'s real
    SHA-256 — never a fabricated shape the real writer would never
    produce (C-004)."""
    sha = hashlib.sha256(diff_file.read_bytes()).hexdigest()
    return review_plan.build_plan(
        ticket=ticket, track="M", path="client", diff_sha256=sha, cap=4,
        override=False,
        passes=[
            review_plan.pass_entry("code-review", "manifest-always", "auto",
                                   None, None, "planned"),
            review_plan.pass_entry("drift", "conditional", "trigger fired",
                                   None, None, "planned"),
            review_plan.pass_entry("deep-impact", "conditional", "trigger fired",
                                   None, None, "planned"),
            review_plan.pass_entry("external", "route", "auto",
                                   "anthropic", "claude", "planned"),
        ])


def _run_with_fake_review_py(clone: Path, ticket: str, monkeypatch, fake_review_py):
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    real_run = subprocess.run

    def _fake_run(argv, *a, **kw):
        if isinstance(argv, list) and argv and argv[0] == sys.executable:
            diff_file = Path(argv[argv.index("--diff") + 1])
            return fake_review_py(ticket, diff_file)
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    return handback._run_planner(ticket)


def test_fake_subprocess_returning_2_after_a_real_plan_is_written_counts_as_success(
    tmp_path, monkeypatch
):
    """AC-8 (guard: already green on step-2's interim exit-code rule, per
    impl-plan-review F-1 — kept as the paired POSITIVE half of the exit-2
    ambiguity): the fake writes a real M-track plan carrying the passed
    file's SHA-256, then returns 2 — "over the cap, plan written" must
    count as success."""
    ticket = "KLC-982"
    clone = _seed_with_live_range(tmp_path, ticket)

    def _fake(ticket, diff_file):
        review_plan.write_plan(ticket, _a_real_m_track_plan(ticket, diff_file))
        return subprocess.CompletedProcess([], 2, stdout="", stderr="")

    result = _run_with_fake_review_py(clone, ticket, monkeypatch, _fake)
    assert result, getattr(result, "reason", "")


def test_fake_subprocess_returning_2_without_a_plan_is_a_failure(tmp_path, monkeypatch):
    """AC-4/AC-8 (the real RED, impl-plan-review F-1's negative twin): the
    fake writes NOTHING and returns 2 — a bare refusal must never be read
    as "over the cap"."""
    ticket = "KLC-983"
    clone = _seed_with_live_range(tmp_path, ticket)

    def _fake(ticket, diff_file):
        return subprocess.CompletedProcess([], 2, stdout="", stderr="[review][err] boom\n")

    result = _run_with_fake_review_py(clone, ticket, monkeypatch, _fake)
    assert not result
    assert "boom" in result.reason or "no review-plan.json" in result.reason or (
        clone / ".klc" / "tickets" / ticket / "review-plan.json").exists() is False


def test_exit_code_other_than_0_or_2_is_a_failure_even_with_a_matching_plan(
    tmp_path, monkeypatch
):
    """AC-4 (guard: already green on step-2's interim rule, impl-plan-review
    F-3): the fake writes a MATCHING plan but returns 1 — a regression that
    trusts the plan alone, without the exit-code guard, must still be
    caught by this one."""
    ticket = "KLC-984"
    clone = _seed_with_live_range(tmp_path, ticket)

    def _fake(ticket, diff_file):
        review_plan.write_plan(ticket, _a_real_m_track_plan(ticket, diff_file))
        return subprocess.CompletedProcess([], 1, stdout="", stderr="")

    result = _run_with_fake_review_py(clone, ticket, monkeypatch, _fake)
    assert not result


def test_unreadable_plan_after_exit_0_is_a_failure_naming_the_unreadable_plan(
    tmp_path, monkeypatch
):
    """AC-4 (RED, impl-plan-review F-3): the fake writes non-JSON to
    `review-plan.json` and returns 0 — the reason must name the unreadable
    plan, not a generic failure."""
    ticket = "KLC-985"
    clone = _seed_with_live_range(tmp_path, ticket)

    def _fake(ticket, diff_file):
        plan_path = clone / ".klc" / "tickets" / ticket / "review-plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text("not json {{{", encoding="utf-8")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    result = _run_with_fake_review_py(clone, ticket, monkeypatch, _fake)
    assert not result
    assert "unreadable" in result.reason
