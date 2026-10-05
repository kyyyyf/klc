"""KLC-166 step-2 — `handback._run_planner` passes `review.py` a REAL diff
FILE (never a range) for the ticket's own range, resolved by
`phase_completion.ticket_diff_range` (step-1): live first, then recorded,
otherwise no usable range at all. The success rule here is still step-2's
interim exit-code rule (`rc in (0, 2)`); step-3 replaces it with the AC-4
post-condition (D-007).

Every test that lets the planner reach a usable range drives the REAL
`scripts/review.py` subprocess (C-004, "mock the real contract" — the KLC-127
bug this ticket fixes was frozen by tests that never fed the real argv to
the real consumer). The one exception is the budget test
(`test_planner_budget_is_shared_by_the_git_and_review_legs`), which pins
`handback._clock` and wraps `subprocess.run` with a counting PASSTHROUGH
(D-008) that still answers every call with the real subprocess, never a
canned value.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import handback  # noqa: E402
import review_plan  # noqa: E402

from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _git,
    _merge,
    _rev_parse,
    _seed_ticket,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def _seed_real_project(clone: Path, ticket: str, **kw) -> Path:
    """`_seed_ticket` plus the one extra file the REAL `review.py` subprocess
    needs: `.klc/config/profile.yml` (the generic profile, as
    `test_klc120_review_cap.py::_seed_project` already does for the same
    real-subprocess reason) and a one-line `spec.md` (design's own rule:
    `_seed_ticket` never writes `spec.md`, every test that lets the real
    `review.py` plan writes it itself)."""
    tdir = _seed_ticket(clone, ticket, **kw)
    (clone / ".klc" / "config").mkdir(parents=True, exist_ok=True)
    (clone / ".klc" / "config" / "profile.yml").write_text(
        "profile: generic\n", encoding="utf-8")
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    return tdir


def _real_diff_bytes(clone: Path, base: str, head: str) -> bytes:
    """The exact bytes `handback._run_planner` materialises for `base..head`
    — recomputed independently (not captured from the deleted temp file) so
    the test can assert the WRITTEN PLAN's `diff_sha256` without needing to
    intercept anything."""
    r = subprocess.run(["git", "diff", base, head], cwd=str(clone), capture_output=True)
    assert r.returncode == 0
    return r.stdout


def _run(clone: Path, ticket: str, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return handback._run_planner(ticket)


def _plan(clone: Path, ticket: str) -> dict:
    import json
    return json.loads((clone / ".klc" / "tickets" / ticket
                       / "review" / "review-plan-r1.json").read_text(encoding="utf-8"))


def test_live_range_diffs_merge_base_to_head_and_matches_the_written_plan(
    tmp_path, monkeypatch
):
    """AC-1: HEAD on the ticket's own branch, `origin/main` present. The
    written plan's `diff_sha256` equals the SHA-256 of
    `git diff merge-base(HEAD, origin/main) HEAD`."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-964"
    base = _rev_parse(clone, "main")
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch="feature/klc-964-add-a-widget")
    head = _rev_parse(clone, "HEAD")
    _seed_real_project(clone, ticket, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)

    result = _run(clone, ticket, monkeypatch)
    assert result, getattr(result, "reason", "")
    expected_sha = hashlib.sha256(_real_diff_bytes(clone, base, head)).hexdigest()
    assert _plan(clone, ticket)["diff_sha256"] == expected_sha


def test_live_range_falls_back_to_plain_main_when_origin_main_is_absent(
    tmp_path, monkeypatch
):
    """AC-1: with no `origin` remote configured, the live range falls back
    to the merge-base with local `main`."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-965"
    base = _rev_parse(clone, "main")
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch="feature/klc-965-add-a-widget")
    head = _rev_parse(clone, "HEAD")
    _git(clone, "remote", "remove", "origin")
    _seed_real_project(clone, ticket, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)

    result = _run(clone, ticket, monkeypatch)
    assert result, getattr(result, "reason", "")
    expected_sha = hashlib.sha256(_real_diff_bytes(clone, base, head)).hexdigest()
    assert _plan(clone, ticket)["diff_sha256"] == expected_sha


def test_recorded_range_used_when_head_is_on_another_tickets_branch(tmp_path, monkeypatch):
    """AC-2/AC-8: HEAD is on a DIFFERENT ticket's branch. The plan is built
    from the RECORDED range, not the live branch, and its `diff_sha256`
    equals the SHA-256 of `git diff <recorded base> <recorded head>`."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-966"
    base = _rev_parse(clone, "main")
    _branch_with_commits(clone, ticket_a, [
        ("widgets/thing.py", "a = 1\n", f"{ticket_a} step-1: add a"),
    ], branch="feature/klc-966-add-a-widget")
    head = _rev_parse(clone, "HEAD")
    _seed_real_project(clone, ticket_a, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES,
                       pre_merge_range={"base": base, "head": head,
                                        "recorded_at_phase": "build",
                                        "recorded_at": "2026-01-01T00:00:00Z"})

    ticket_b = "KLC-967"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-967-other")

    result = _run(clone, ticket_a, monkeypatch)
    assert result, getattr(result, "reason", "")
    expected_sha = hashlib.sha256(_real_diff_bytes(clone, base, head)).hexdigest()
    assert _plan(clone, ticket_a)["diff_sha256"] == expected_sha


def test_recorded_range_used_when_the_live_diff_touches_only_dot_klc_paths(
    tmp_path, monkeypatch
):
    """AC-2: the live range's only changed path is under `.klc/` — not a
    usable live range. The recorded range is used instead."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-968"
    recorded_base = _rev_parse(clone, "main")
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    recorded_head = _rev_parse(clone, "HEAD")
    _merge(clone, ticket, "ff-only")           # origin/main now == recorded_head
    _seed_real_project(clone, ticket, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES,
                       pre_merge_range={"base": recorded_base, "head": recorded_head,
                                        "recorded_at_phase": "build",
                                        "recorded_at": "2026-01-01T00:00:00Z"})
    (clone / ".klc" / "tickets" / ticket / "note.md").write_text("note\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", f"{ticket}: ack artefact only")

    result = _run(clone, ticket, monkeypatch)
    assert result, getattr(result, "reason", "")
    expected_sha = hashlib.sha256(
        _real_diff_bytes(clone, recorded_base, recorded_head)).hexdigest()
    assert _plan(clone, ticket)["diff_sha256"] == expected_sha


def test_recorded_range_used_when_no_merge_base_is_computable(tmp_path, monkeypatch):
    """AC-2 (trigger 2): HEAD sits on an orphan branch sharing no history
    with `main` or `origin/main`. With a valid recorded range present, the
    planner falls through to it (a SUCCESS path, not AC-3's all-unusable
    path)."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-969"
    recorded_base = _rev_parse(clone, "main")
    _git(clone, "checkout", "main")
    (clone / "widgets").mkdir(parents=True, exist_ok=True)
    (clone / "widgets" / "thing.py").write_text("a = 1\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", f"{ticket} step-1: add a")
    recorded_head = _rev_parse(clone, "HEAD")
    _seed_real_project(clone, ticket, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES,
                       pre_merge_range={"base": recorded_base, "head": recorded_head,
                                        "recorded_at_phase": "build",
                                        "recorded_at": "2026-01-01T00:00:00Z"})

    _git(clone, "checkout", "--orphan", "feature/klc-969-orphan")
    _git(clone, "rm", "-rf", "--cached", ".")
    (clone / "orphan.txt").write_text("o\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", f"{ticket} orphan: unrelated history")

    result = _run(clone, ticket, monkeypatch)
    assert result, getattr(result, "reason", "")
    expected_sha = hashlib.sha256(
        _real_diff_bytes(clone, recorded_base, recorded_head)).hexdigest()
    assert _plan(clone, ticket)["diff_sha256"] == expected_sha


def test_no_usable_range_writes_no_plan_and_names_both_the_branch_and_the_missing_recorded_range(
    tmp_path, monkeypatch
):
    """AC-3: HEAD on another ticket's branch, no recorded range at all for
    the acked ticket. No `review.py` subprocess runs (a monkeypatched
    `subprocess.run` that raises if called proves it), no plan is written,
    and the reason names the foreign branch and the missing recorded range."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-966"
    _seed_real_project(clone, ticket_a, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)

    ticket_b = "KLC-967"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-967-other")

    real_run = subprocess.run

    def _boom_on_review_py_only(argv, *a, **kw):
        # D-008: never fake a git call a real repository can answer — only
        # the review.py argv must be unreachable here.
        if isinstance(argv, list) and argv and argv[0] == sys.executable:
            raise AssertionError("no review.py subprocess must run when no range is usable")
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _boom_on_review_py_only)
    result = _run(clone, ticket_a, monkeypatch)
    assert not result
    assert "KLC-967" in result.reason
    assert "no recorded pre-merge range for this ticket" in result.reason
    assert not (clone / ".klc" / "tickets" / ticket_a / "review" / "review-plan-r1.json").exists()


@pytest.mark.parametrize("ticks,expect_review_call,note", [
    ([0.0, 30.0, 60.0], True,
     "budget shrinks: review.py gets 120 - elapsed, well under 120"),
    ([0.0, 200.0], False,
     "budget already exhausted after range resolution: no review.py call at all"),
])
def test_planner_budget_is_shared_by_the_git_and_review_legs(
    tmp_path, monkeypatch, ticks, expect_review_call, note
):
    """Q-006/D-006 (impl-plan-review F-2): `_run_planner` keeps ONE
    120-second budget across both the `git diff` materialisation and the
    `review.py` leg. An advancing fake `handback._clock` (D-008 counting
    passthrough on `subprocess.run`, never a canned git answer) proves the
    `review.py` call's `timeout` shrinks by elapsed time, and an
    already-exhausted clock proves NO `review.py` call happens at all."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-970"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch="feature/klc-970-add-a-widget")
    _seed_real_project(clone, ticket, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)

    tick_iter = iter(ticks)
    monkeypatch.setattr(handback, "_clock", lambda: next(tick_iter))

    review_calls = []
    real_run = subprocess.run

    def _counting_passthrough(argv, *a, **kw):
        if isinstance(argv, list) and argv and argv[0] == sys.executable:
            review_calls.append(kw.get("timeout"))
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _counting_passthrough)

    result = _run(clone, ticket, monkeypatch)
    if expect_review_call:
        assert len(review_calls) == 1, note
        assert 0 < review_calls[0] < 120, note
    else:
        assert len(review_calls) == 0, note
        assert not result
        assert "budget" in result.reason
