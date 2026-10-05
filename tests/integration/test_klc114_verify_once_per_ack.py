"""KLC-174 note: the ack no longer executes any VERIFY, so the once-per-ack
cache is moot and this test now pins zero executions. Original intent below.

KLC-114 step-12 (review round 1, HIGH; AC-1/AC-11/C-005): `can_complete_build`
runs `step_verify.check_steps` then `step_ledger.verify_build_steps`, and
each independently called `verify_runner.run` on the SAME command for the
SAME step — doubling every step's VERIFY execution (and its wall-clock
cost against the shared arm budget) on every M/L build ack. A per-ack
Verdict cache, keyed by (ticket, step id, exact command string), makes
each step's VERIFY execute at most once per `can_complete_build` call.

The only pre-existing call-count-shaped test
(`tests/test_ac_test_coverage.py::test_can_complete_build_shares_one_verify_arm_deadline_across_all_three_checks`)
uses track M but only SPIES on `evidence_gate.check_evidence`/
`step_verify.check_steps`/`ac_test_coverage.check`'s own *deadline*
argument — never counts `verify_runner.run` invocations, so it never
caught this. No existing test uses XS here (XS would make `step_verify`
short-circuit to `mode == "skip"` before ever calling `verify_runner.run`
at all, which would hide the bug the other direction — this fixture
deliberately uses M so BOTH arms actually run).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import klc114_helpers as h  # noqa: E402


def test_two_real_passing_steps_execute_verify_zero_times_at_ack(tmp_path, monkeypatch):
    """AC-1/AC-11/C-005: a 2-step M-track fixture, each step with real
    commits satisfying TDD order and scope, driven through
    `can_complete_build(ticket, repo, persist=True)` — `verify_runner.run`
    executes ZERO times (KLC-174: the ack reads steps.json; it was once per
    step before)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-VC01"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:ack-needed", "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        f"---\nticket: {ticket}\nkind: tech\n---\n\n"
        "## Acceptance Criteria\n\n## Estimate\n- total: 1\n", encoding="utf-8")
    (ticket_dir / "test-plan.md").write_text(
        f"---\nticket: {ticket}\nkind: test-plan\n---\n\n"
        "## Acceptance coverage\n\n## Edge cases\n- n/a\n", encoding="utf-8")
    plan = "# Implementation plan\n\n" + "".join(
        h.step_plan(f"step-{n}", verify="`sh -c \"echo 1 passed\"`",
                   expected="`1 passed`", affected=f"`core/skills/f{n}.py`")
        for n in (1, 2))
    (ticket_dir / "impl-plan.md").write_text(plan, encoding="utf-8")

    repo = h.make_repo(tmp_path)
    for n in (1, 2):
        h.commit(repo, {f"tests/test_f{n}.py": "# test"}, f"{ticket} step-{n}: add test")
        h.commit(repo, {f"core/skills/f{n}.py": "# impl"}, f"{ticket} step-{n}: implement")
    h.seed_steps(ticket_dir, repo)   # KLC-174: the recorded verifies the ack reads

    import verify_runner
    calls = []
    real_run = verify_runner.run

    def counting_run(command, **kw):
        calls.append(command)
        return real_run(command, **kw)

    monkeypatch.setattr(verify_runner, "run", counting_run)

    from core.skills.phase_completion import can_complete_build
    ok, msg = can_complete_build(ticket, repo, persist=True)

    assert ok, msg
    assert calls == [], f"KLC-174: the ack executes no VERIFY, saw: {calls}"
