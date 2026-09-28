"""KLC-114 step-3: judge_step records `unverified` with a named reason for
each of the four ways a verdict cannot be reached — never `green`, and
never `red` for the absence of commits (AC-5)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc114_helpers as h  # noqa: E402
import step_ledger as sl  # noqa: E402


def test_runner_unverified_state_propagates_reason(tmp_path, monkeypatch):
    """AC-5: `verify_runner.run` returning UNVERIFIED (here, a per-command
    budget overrun — the VERIFY command sleeps past its own `budget_s`)
    propagates the runner's own named reason, never green/red. Distinct from
    the shared-arm-deadline case below: this is `verify_runner.run`'s OWN
    reason, surfacing only once the re-run is actually attempted."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-UR01"
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="`python3 -c \"import time; time.sleep(5)\"`",
        expected="`2 passed`")
    h.make_ticket(tmp_path, ticket, "M", plan)
    repo = h.make_repo(tmp_path, "repo1")
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")

    v = sl.judge_step(ticket, 1, repo=str(repo), budget_s=0.2)

    assert v.state == sl.UNVERIFIED
    assert "budget-exceeded" in v.reason


def test_placeholder_verify_or_expected_is_unverified(tmp_path, monkeypatch):
    """AC-5: a step's `VERIFY:`/`Expected:` field is itself a placeholder —
    `step_verify.expected_token` cannot isolate a token — so the pass records
    unverified, never green."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-UR02"
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="TBD", expected="TBD")
    h.make_ticket(tmp_path, ticket, "M", plan)

    v = sl.judge_step(ticket, 1, repo=str(tmp_path))

    assert v.state == sl.UNVERIFIED
    assert v.reason == "verify-placeholder"


def test_no_attributable_commits_is_unverified_never_red(tmp_path, monkeypatch):
    """AC-5/Q-002: zero commits carry the step's `KLC-NNN step-N` key (a
    squashed or omitted commit key) → unverified: no-commits, never red —
    absence of evidence is not evidence of failure."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-UR03"
    plan = "# Implementation plan\n\n" + h.step_plan("step-1")
    h.make_ticket(tmp_path, ticket, "M", plan)
    repo = h.make_repo(tmp_path, "repo3")
    h.commit(repo, {"README.md": "unrelated"}, "unrelated commit, no step key")

    v = sl.judge_step(ticket, 1, repo=str(repo))

    assert v.state == sl.UNVERIFIED
    assert v.reason == "no-commits"


def test_budget_exceeded_is_unverified_using_shared_deadline(tmp_path, monkeypatch):
    """AC-5/C-005: an already-exhausted shared deadline (the SAME object
    `can_complete_build` computed) is unverified, never green/red, and the
    pass never opens a second budget — `verify_runner.run` must not even be
    invoked once the deadline has passed."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-UR04"
    plan = "# Implementation plan\n\n" + h.step_plan("step-1")
    h.make_ticket(tmp_path, ticket, "M", plan)
    repo = h.make_repo(tmp_path, "repo4")
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")

    def _boom(*a, **kw):
        raise AssertionError("verify_runner.run must not run past an exhausted deadline")
    monkeypatch.setattr(sl.verify_runner, "run", _boom)

    v = sl.judge_step(ticket, 1, repo=str(repo), deadline=time.monotonic() - 1)

    assert v.state == sl.UNVERIFIED
    assert "arm-budget-exhausted" in v.reason
