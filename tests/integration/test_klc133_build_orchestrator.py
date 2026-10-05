"""AC-6/AC-7: every headless build dispatch (step, per-step review, fix
pass) records one attempt tagged `telemetry_phase="build"`, the step
number, and its `run_pass`, and an injected `dispatch` still receives
exactly today's arguments.
"""
from __future__ import annotations

import json
import textwrap
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import klc114_helpers as h  # noqa: E402

from _klc133_support import (  # noqa: E402
    FakeAnthropic,
    all_attempts,
    fixture_json,
    seed_ticket,
    klc133_hermetic,  # noqa: F401  (autouse fixture, must be in module namespace)
)


_PLAN_ONE_STEP = textwrap.dedent("""\
    ---
    ticket: KLC-B1
    kind: impl-plan
    ---

    ## step-1 — first step

    - **Goal:** do first thing
    - **Interfaces:** `def first() -> None`
    - **Expected:** first called
    - **VERIFY:** pytest
    - **COMMIT:** KLC-B1 step-1: first step
    - **Affected:** src/first.py
    - Depends-on: none
    - **Code sketch:**

    ```python
    def first(): pass
    ```
""")

_SPEC = textwrap.dedent("""\
    ---
    ticket: KLC-B1
    kind: feature
    authority: human
    risk_tags: []
    ---

    ## Goals
    Test the build orchestrator's telemetry tags.

    ## Acceptance Criteria
    - [ ] AC-1: tags dispatches
""")


def _envelope_with_result(result_text: str) -> str:
    env = fixture_json("envelope-single.json")
    env["result"] = result_text
    return json.dumps(env)


def _seed_build_ticket(project: Path, *, track: str = "M") -> Path:
    tdir = seed_ticket(project, "KLC-B1", track=track, phase="build:work")
    (tdir / "impl-plan.md").write_text(
        _PLAN_ONE_STEP.replace("KLC-B1", "KLC-B1"), encoding="utf-8")
    (tdir / "spec.md").write_text(_SPEC, encoding="utf-8")
    return tdir


def _blocking_reply():
    """The first `per-step-review` reply is one CRITICAL finding; the
    second is `[]`. Every `build` reply is a plain successful response."""
    counts = {"per-step-review": 0}

    def reply(resolved, prompt):
        if resolved.phase == "per-step-review":
            counts["per-step-review"] += 1
            if counts["per-step-review"] == 1:
                findings = json.dumps([{
                    "rule_name": "blocking-rule", "severity": "CRITICAL",
                    "file": "src/first.py", "line": 1,
                    "title": "blocking issue", "body": "fix it",
                    "fix": None, "reviewer": "per-step",
                }])
                return (0, _envelope_with_result(findings), "")
            return (0, _envelope_with_result("[]"), "")
        return (0, _envelope_with_result("Green.\n"), "")

    return reply


def test_one_tagged_provider_attempt_per_headless_dispatch_on_a_blocking_step(
        klc133_hermetic, monkeypatch):
    """AC-6 (KLC-174: step state pinned, no git in this hermetic project): one attempt per headless dispatch: telemetry_phase="build",
    step=<n> and run_pass in {"step", "per-step-review", "per-step-fix"}
    (D-115: run_pass counts {"step": 1, "per-step-review": 2,
    "per-step-fix": 1}), all provider, all step == 1, none with a reviewer
    tag."""
    import runner
    import build_orchestrator as bo

    project = klc133_hermetic
    _seed_build_ticket(project)
    h.pin_step_state(monkeypatch, [1])
    fake = FakeAnthropic(_blocking_reply())
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)

    rc = bo.run_build("KLC-B1")
    assert rc == 0  # the fix pass resolves the blocking finding; the build succeeds

    attempts = all_attempts("KLC-B1", "build")
    assert len(attempts) == 4
    assert all(a["source"] == "provider" for a in attempts)
    assert all(a["step"] == 1 for a in attempts)
    assert all("reviewer" not in a for a in attempts)
    assert Counter(a["run_pass"] for a in attempts) == Counter(
        {"step": 1, "per-step-review": 2, "per-step-fix": 1})


def test_review_llm_passes_per_ticket_is_unchanged_by_build_dispatches(
        klc133_hermetic, monkeypatch):
    """AC-6: build's four tagged attempts (none reviewer-tagged) must not
    leak into the reviewer-pass counter — review_llm_passes_per_ticket for
    track M stays None."""
    import runner
    import build_orchestrator as bo
    import metrics

    project = klc133_hermetic
    _seed_build_ticket(project)
    h.pin_step_state(monkeypatch, [1])
    fake = FakeAnthropic(_blocking_reply())
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)

    bo.run_build("KLC-B1")
    assert len(all_attempts("KLC-B1", "build")) == 4

    metrics.cmd_rollup(None)
    payload = json.loads(
        (project / ".klc" / "knowledge" / "process-metrics.json")
        .read_text(encoding="utf-8"))
    assert payload["per_track"]["M"]["review_llm_passes_per_ticket"] is None


def test_injected_dispatch_receives_exactly_todays_arguments(
        klc133_hermetic, monkeypatch):
    """AC-6: pin — an injected dispatch with TODAY's minimal signature
    (no `klc_telemetry` marker) runs a whole build without TypeError; the
    step/run_pass tags are only ever added for the DEFAULT telemetry
    dispatch. An XS-track ticket skips per-step review entirely, so the
    only dispatch shape exercised is the plain "build" step call, which
    did not pass `inputs=` before KLC-133 and KLC-172 respectively."""
    import build_orchestrator as bo

    project = klc133_hermetic
    _seed_build_ticket(project, track="XS")
    h.pin_step_state(monkeypatch, [1])

    calls: list[str] = []

    def stub(phase_id, prompt_path, out_path, *, inputs=None, track=None):
        calls.append(phase_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("Green.\n", encoding="utf-8")
        return 0

    rc = bo.run_build("KLC-B1", dispatch=stub)
    assert rc == 0
    assert calls == ["build"]
