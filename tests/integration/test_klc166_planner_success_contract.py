"""KLC-166 step-3 — AC-4/AC-5: `handback._run_planner` reports success only
when `review.py` exited 0 or 2 AND `review-plan.json` now exists for the
ticket AND its `diff_sha256` equals the SHA-256 of the diff file it passed;
otherwise the reason is `review.py`'s last non-empty stderr line, or names
the missing/unreadable/mismatched plan. `handback._record` prints exactly
one note on every planner failure (a reported one, or a raised
`subprocess.TimeoutExpired`/`OSError`), never the old `RecordRefused` hint.

Every test here drives the REAL `review.py` subprocess (C-004); the two
tests that need to see a corrupted or substituted input use a
`subprocess.run` PASSTHROUGH (D-008) — the real call still happens, the
fake only mutates the on-disk plan afterwards or swaps the `--diff` value
before the call. `review_plan.write_plan` itself can never be
monkeypatched for this purpose: `review.py` runs in a separate process, so
an in-process patch of it would never be seen there.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import handback  # noqa: E402
import metrics  # noqa: E402

from _klc128_fixtures import _bare_and_clone, _branch_with_commits, _seed_ticket  # noqa: E402

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def _seed_real_project(clone: Path, ticket: str, *, with_spec: bool = True, **kw) -> Path:
    tdir = _seed_ticket(clone, ticket, **kw)
    (clone / ".klc" / "config").mkdir(parents=True, exist_ok=True)
    (clone / ".klc" / "config" / "profile.yml").write_text(
        "profile: generic\n", encoding="utf-8")
    if with_spec:
        (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    return tdir


def _seed_with_live_range(tmp_path: Path, ticket: str, *, with_spec: bool = True) -> Path:
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch=f"feature/{ticket.lower()}-add-a-widget")
    _seed_real_project(clone, ticket, with_spec=with_spec, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)
    return clone


def _plan_path(clone: Path, ticket: str) -> Path:
    return clone / ".klc" / "tickets" / ticket / "review-plan.json"


def test_success_requires_review_py_exit_0_or_2_and_a_plan_with_the_matching_diff_sha256(
    tmp_path, monkeypatch
):
    """AC-4 (both halves): a normal real run succeeds (exit in {0,2}, a
    plan exists, its `diff_sha256` matches). A SECOND ticket's real run,
    with a `subprocess.run` passthrough that corrupts the WRITTEN plan's
    `diff_sha256` right after the real `review.py` call returns, is then
    reported as a failure — proving the check reads the plan's content,
    not just the exit code."""
    ticket_ok = "KLC-975"
    clone = _seed_with_live_range(tmp_path, ticket_ok)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result_ok = handback._run_planner(ticket_ok)
    assert result_ok, getattr(result_ok, "reason", "")
    assert _plan_path(clone, ticket_ok).is_file()

    ticket_bad = "KLC-976"
    _branch_with_commits(clone, ticket_bad, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_bad} step-1: add b"),
    ], branch=f"feature/{ticket_bad.lower()}-add-a-gizmo")
    _seed_real_project(clone, ticket_bad, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)

    real_run = subprocess.run

    def _corrupt_after_real_run(argv, *a, **kw):
        r = real_run(argv, *a, **kw)
        if isinstance(argv, list) and argv and argv[0] == sys.executable:
            plan_path = _plan_path(clone, ticket_bad)
            if plan_path.is_file():
                data = json.loads(plan_path.read_text(encoding="utf-8"))
                data["diff_sha256"] = "0" * 64
                plan_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return r

    monkeypatch.setattr(subprocess, "run", _corrupt_after_real_run)
    result_bad = handback._run_planner(ticket_bad)
    assert not result_bad
    assert "diff_sha256" in result_bad.reason


def test_failure_reason_carries_review_pys_last_stderr_line_on_an_unresolvable_diff_ref(
    tmp_path, monkeypatch
):
    """AC-4: a passthrough swaps the `--diff` value to the literal
    `main...HEAD` (the historical bug) right before the real `review.py`
    call. The reported reason is exactly `review.py`'s last non-empty
    stderr line, not a generic wrapper message."""
    ticket = "KLC-977"
    clone = _seed_with_live_range(tmp_path, ticket)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    real_run = subprocess.run

    def _swap_diff_to_a_range(argv, *a, **kw):
        if isinstance(argv, list) and argv and argv[0] == sys.executable:
            argv = list(argv)
            argv[argv.index("--diff") + 1] = "main...HEAD"
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _swap_diff_to_a_range)
    result = handback._run_planner(ticket)
    assert not result
    assert result.reason.startswith(
        "[review][err] --diff is neither a file nor a resolvable git ref")


def test_take_prints_exactly_one_reason_note_and_exits_0_on_a_reported_planner_failure(
    tmp_path, monkeypatch, capsys
):
    """AC-5: `take` over the AC-3 no-usable-range case prints exactly one
    note (`handback: note: planner did not write a review plan (<reason>);
    pass not recorded`), exits 0, and still stores the verdict."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-978"
    _seed_real_project(clone, ticket_a, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)
    ticket_b = "KLC-979"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-979-other")
    monkeypatch.setenv("PROJECT_ROOT", str(clone))

    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps({"findings": [], "decisions_to_confirm": []}),
                     encoding="utf-8")
    rc = handback.take("code-review", ticket_a, vfile)
    assert rc == 0

    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    note_lines = [ln for ln in lines if ln.startswith("handback: note:")]
    assert len(note_lines) == 1
    assert note_lines[0].startswith(
        "handback: note: planner did not write a review plan (")
    assert note_lines[0].endswith("); pass not recorded")
    assert "run the planner (--plan-only)" not in out
    assert (clone / ".klc" / "tickets" / ticket_a
           / "review" / "code-review-findings.json").is_file()


@pytest.mark.parametrize("exc_factory", [
    lambda: subprocess.TimeoutExpired(cmd=["review.py"], timeout=120),
    lambda: OSError("boom"),
])
def test_take_uses_the_exception_text_as_the_reason_on_timeout_or_oserror(
    tmp_path, monkeypatch, capsys, exc_factory
):
    """AC-5: `_run_planner` raising `TimeoutExpired`/`OSError` also degrades
    to exactly ONE note whose reason is the exception text, never the old
    `RecordRefused` hint, and never a second 'planner failed (...)' note
    (spec-review F-5)."""
    project_root = tmp_path / "proj"
    tdir = project_root / ".klc" / "tickets" / "KLC-980"
    tdir.mkdir(parents=True)
    meta = {"ticket": "KLC-980", "kind": "bug", "kind_source": "user",
           "phase": "build:work", "phase_history": [], "track": "M",
           "route_hint": "M", "route_confidence": "high", "affected_modules": [],
           "estimate": None, "layer": "code", "jira_url": None,
           "created": "2026-01-01T00:00:00Z"}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))

    exc = exc_factory()

    def _boom(ticket):
        raise exc

    monkeypatch.setattr(handback, "_run_planner", _boom)

    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps({"findings": [], "decisions_to_confirm": []}),
                     encoding="utf-8")
    rc = handback.take("code-review", "KLC-980", vfile)
    assert rc == 0

    out = capsys.readouterr().out
    note_lines = [ln for ln in out.splitlines() if ln.startswith("handback: note:")]
    assert len(note_lines) == 1
    assert note_lines[0] == (
        f"handback: note: planner did not write a review plan ({exc}); "
        "pass not recorded")
    assert "run the planner (--plan-only)" not in out


def test_real_review_py_refusal_on_a_ticket_with_no_spec_md_writes_no_plan_and_yields_the_ac5_note(
    tmp_path, monkeypatch, capsys
):
    """AC-8: a real `review.py` refusal (a ticket with no `spec.md`, a
    refusal the tool already raises today) writes no plan — AC-4 must read
    that as a failure, carried through `handback.take` to the AC-5 note."""
    ticket = "KLC-981"
    clone = _seed_with_live_range(tmp_path, ticket, with_spec=False)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps({"findings": [], "decisions_to_confirm": []}),
                     encoding="utf-8")
    rc = handback.take("code-review", ticket, vfile)
    assert rc == 0
    assert not _plan_path(clone, ticket).is_file()
    out = capsys.readouterr().out
    assert "handback: note: planner did not write a review plan (" in out
