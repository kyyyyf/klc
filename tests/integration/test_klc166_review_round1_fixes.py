"""KLC-166 step-5 — review round 1 fixes (external code review).

Three findings against the step-1..4 build:

- F-1 (MEDIUM): `handback._record` caught only `(OSError,
  subprocess.SubprocessError)` around the planner call, so ANY other
  exception — an `ImportError`/attribute error from the lazy
  `import phase_completion`, or any non-OS exception
  `phase_completion.ticket_diff_range` might raise — escaped `take` AFTER
  the verdict was already stored, breaking C-003/AC-5 ("planning failure
  is one note, never a failed hand-back"). Also, `_run_planner`'s
  `review.py` subprocess call used `text=True` with no `errors=` handling,
  so a non-UTF-8 byte on `review.py`'s stdout/stderr would raise
  `UnicodeDecodeError` out of `subprocess.run` itself.
- F-2 (LOW): a plan `_plan_outcome` rejects (a `diff_sha256` mismatch, or
  an exit code outside {0, 2} with a plan written) was left on disk at
  `review-plan.json`. The next `take` then saw `review-plan.json` as
  PRESENT and skipped the planner entirely (`_record` only re-plans when
  the file is MISSING), so a rejected plan blocked every future `take` on
  that ticket forever.

This file proves both fixes against the real `review.py` subprocess
(C-004) wherever one is reachable; the first test bypasses the subprocess
entirely by making `phase_completion.ticket_diff_range` itself raise,
which is the cheapest hermetic way to prove ANY exception (not just
OSError/SubprocessError) degrades to one note.
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
import phase_completion  # noqa: E402

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


def _review_dir(clone: Path, ticket: str) -> Path:
    return clone / ".klc" / "tickets" / ticket / "review"


def _write_verdict(tmp_path: Path) -> Path:
    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps({"findings": [], "decisions_to_confirm": []}),
                     encoding="utf-8")
    return vfile


# --- F-1: ANY planner exception stays one note, not just OSError/SubprocessError ----

def test_a_non_os_exception_from_ticket_diff_range_stays_one_note_and_take_exits_0(
    tmp_path, monkeypatch, capsys
):
    """F-1(a): `phase_completion.ticket_diff_range` (reached only AFTER
    `handback`'s lazy `import phase_completion` already succeeded) raises a
    plain `ValueError` — not `OSError`/`subprocess.SubprocessError`. Before
    the fix `_record`'s narrow `except (OSError, subprocess.SubprocessError)`
    does not catch it, so it escapes `take` after the verdict is already
    stored (C-003 violation). After the fix `take` must still print exactly
    one AC-5 note, exit 0, and keep the stored verdict."""
    project_root = tmp_path / "proj"
    tdir = project_root / ".klc" / "tickets" / "KLC-986"
    tdir.mkdir(parents=True)
    meta = {"ticket": "KLC-986", "kind": "bug", "kind_source": "user",
           "phase": "build:work", "phase_history": [], "track": "M",
           "route_hint": "M", "route_confidence": "high", "affected_modules": [],
           "estimate": None, "layer": "code", "jira_url": None,
           "created": "2026-01-01T00:00:00Z"}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))

    def _boom(ticket):
        raise ValueError("boom from ticket_diff_range")

    monkeypatch.setattr(phase_completion, "ticket_diff_range", _boom)

    vfile = _write_verdict(tmp_path)
    rc = handback.take("code-review", "KLC-986", vfile)
    assert rc == 0

    out = capsys.readouterr().out
    note_lines = [ln for ln in out.splitlines() if ln.startswith("handback: note:")]
    assert len(note_lines) == 1
    assert note_lines[0] == (
        "handback: note: planner did not write a review plan "
        "(boom from ticket_diff_range); pass not recorded")
    assert "run the planner (--plan-only)" not in out
    assert (tdir / "review" / "code-review-findings.json").is_file()


def test_review_py_printing_a_non_utf8_byte_does_not_crash_take(
    tmp_path, monkeypatch, capsys
):
    """F-1(b): `_run_planner`'s `review.py` subprocess call must decode
    with `errors="replace"`. A passthrough swaps the real `review.py`
    script for a tiny stand-in that writes one invalid UTF-8 byte to
    stderr and exits 2 (a refusal, no plan written) — every `git` call
    still goes through the real repository (D-008). Before the fix,
    `text=True` with no `errors=` makes `subprocess.run` itself raise
    `UnicodeDecodeError`, which also escapes the narrow except in
    `_record`. After both fixes, `take` must print exactly one note whose
    reason is the DECODED (replacement-charactered) stderr line, not a
    generic decode-error message, and must exit 0."""
    ticket = "KLC-989"
    clone = _seed_with_live_range(tmp_path, ticket)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    fake_script = tmp_path / "fake_review.py"
    fake_script.write_text(
        "import sys\n"
        "sys.stderr.buffer.write(b'[review][err] broken \\xff byte\\n')\n"
        "sys.exit(2)\n",
        encoding="utf-8")

    real_run = subprocess.run

    def _swap_review_py_for_the_fake_script(argv, *a, **kw):
        if isinstance(argv, list) and argv and argv[0] == sys.executable:
            argv = list(argv)
            argv[1] = str(fake_script)
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _swap_review_py_for_the_fake_script)

    vfile = _write_verdict(tmp_path)
    rc = handback.take("code-review", ticket, vfile)
    assert rc == 0

    out = capsys.readouterr().out
    note_lines = [ln for ln in out.splitlines() if ln.startswith("handback: note:")]
    assert len(note_lines) == 1
    assert "broken" in note_lines[0] and "byte" in note_lines[0]
    assert "run the planner (--plan-only)" not in out
    assert not _plan_path(clone, ticket).is_file()


# --- F-2: a plan rejected in THIS call is moved aside, so the next `take` re-plans --

def test_second_take_after_a_rejected_plan_runs_the_planner_again_and_records_cleanly(
    tmp_path, monkeypatch, capsys
):
    """F-2: the first `take` runs the real `review.py`, then a
    `subprocess.run` passthrough corrupts the WRITTEN plan's
    `diff_sha256` right after the real call returns (D-008) — exactly the
    `_plan_outcome` mismatch rejection. Before the fix the rejected plan is
    left at `review-plan.json`, so a second `take` sees a plan file
    present, skips `_run_planner` entirely, and `record_pass` happily
    flips `code-review` to `executed` against a plan for the WRONG diff.
    After the fix the rejected plan is moved aside to
    `review/review-plan.rejected-<ts>.json`; the second `take` (with the
    real, unmodified `subprocess.run` restored) must re-run the planner
    from scratch, write a FRESH plan matching the real diff, and record
    against THAT plan."""
    ticket = "KLC-990"
    clone = _seed_with_live_range(tmp_path, ticket)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plan_file = _plan_path(clone, ticket)
    review_dir = _review_dir(clone, ticket)

    real_run = subprocess.run

    def _corrupt_after_real_run(argv, *a, **kw):
        r = real_run(argv, *a, **kw)
        if isinstance(argv, list) and argv and argv[0] == sys.executable and plan_file.is_file():
            data = json.loads(plan_file.read_text(encoding="utf-8"))
            data["diff_sha256"] = "0" * 64
            plan_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return r

    monkeypatch.setattr(subprocess, "run", _corrupt_after_real_run)

    vfile = _write_verdict(tmp_path)
    rc1 = handback.take("code-review", ticket, vfile)
    assert rc1 == 0
    out1 = capsys.readouterr().out
    assert "pass not recorded" in out1
    assert not plan_file.is_file(), (
        "a plan _plan_outcome rejected in THIS call must be moved aside, "
        "not left at review-plan.json")
    rejected = sorted(review_dir.glob("review-plan.rejected-*.json"))
    assert len(rejected) == 1
    rejected_data = json.loads(rejected[0].read_text(encoding="utf-8"))
    assert rejected_data["diff_sha256"] == "0" * 64

    monkeypatch.setattr(subprocess, "run", real_run)  # second take: real review.py, no corruption
    rc2 = handback.take("code-review", ticket, vfile)
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "accepted" in out2
    assert "pass not recorded" not in out2
    assert plan_file.is_file()
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    code_review_pass = next(p for p in plan["passes"] if p["reviewer"] == "code-review")
    assert code_review_pass["status"] == "executed"
    assert len(sorted(review_dir.glob("review-plan.rejected-*.json"))) == 1, (
        "the second take's fresh plan must not itself be rejected again")


def test_a_pre_existing_plan_is_never_moved_aside_by_plan_outcome(tmp_path, monkeypatch):
    """F-2 guard: `_plan_outcome` must move aside only a plan `review.py`
    wrote in THIS call, never one that already existed BEFORE the call
    (A-002: such a plan can only be a concurrent `review.py` run's output,
    and is left exactly as `write_plan` wrote it). Calling `_plan_outcome`
    directly with `pre_existing=True` against a plan whose `diff_sha256`
    does not match the given diff file must report failure and leave the
    plan file untouched."""
    clone = _seed_with_live_range(tmp_path, "KLC-991")
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    plan_file = _plan_path(clone, "KLC-991")
    plan_file.write_text(json.dumps({"diff_sha256": "f" * 64, "passes": []}, indent=2) + "\n",
                         encoding="utf-8")
    diff_file = tmp_path / "some.diff"
    diff_file.write_bytes(b"diff --git a/x b/x\n")
    completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")

    result = handback._plan_outcome("KLC-991", completed, diff_file, pre_existing=True)
    assert not result
    assert plan_file.is_file(), "a pre-existing plan must never be moved aside"
    assert json.loads(plan_file.read_text(encoding="utf-8"))["diff_sha256"] == "f" * 64
