"""KLC-042: build orchestrator — ledger, dispatch loop, resume, CLI verb."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_PLAN = textwrap.dedent("""\
    ---
    ticket: KLC-T2
    kind: impl-plan
    ---

    ## step-1 — first step

    - **Goal:** do first thing
    - **Interfaces:** `def first() -> None`
    - **Expected:** first called
    - **VERIFY:** pytest
    - **COMMIT:** KLC-T2 step-1: first step
    - **Affected:** src/first.py
    - Depends-on: none
    - **Code sketch:**

    ```python
    def first(): pass
    ```

    ## step-2 — second step

    - **Goal:** do second thing
    - **Interfaces:** `def second() -> None`
    - **Expected:** second called
    - **VERIFY:** pytest
    - **COMMIT:** KLC-T2 step-2: second step
    - **Affected:** src/second.py
    - Depends-on: step-1
    - **Code sketch:**

    ```python
    def second(): pass
    ```
""")

_SPEC = textwrap.dedent("""\
    ---
    ticket: KLC-T2
    kind: feature
    authority: human
    risk_tags: []
    ---

    ## Goals
    Test the build orchestrator.

    ## Acceptance Criteria
    - [ ] AC-1: orchestrator dispatches each step
""")

_META = json.dumps({
    "ticket": "KLC-T2",
    "track": "M",
    "kind": "feature",
    "phase": "build:work",
    "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
    "affected_modules": ["core/skills"],
    "risk_tags": [],
})


@pytest.fixture()
def ticket_dir(tmp_path):
    tdir = tmp_path / ".klc" / "tickets" / "KLC-T2"
    tdir.mkdir(parents=True)
    (tdir / "impl-plan.md").write_text(_PLAN)
    (tdir / "spec.md").write_text(_SPEC)
    (tdir / "meta.json").write_text(_META)
    return tmp_path


# ---------------------------------------------------------------------------
# step-1 tests: Ledger roundtrip
# ---------------------------------------------------------------------------

def test_ledger_roundtrip(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from build_ledger import Ledger
    led = Ledger.from_plan("KLC-T2")
    assert len(led.steps) == 2
    assert led.steps[0].state == "pending"
    assert led.steps[1].state == "pending"
    assert led.first_pending() == 1

    led.mark("step-1", "green", model="claude-sonnet-4-6")
    led.save()

    led2 = Ledger.load("KLC-T2")
    assert led2.steps[0].state == "green"
    assert led2.steps[0].model == "claude-sonnet-4-6"
    assert led2.steps[0].ts is not None
    import re as _re
    assert _re.match(r"\d{4}-\d{2}-\d{2}T", led2.steps[0].ts)
    assert led2.first_pending() == 2


def test_ledger_from_plan_preserves_green(ticket_dir, monkeypatch):
    """Re-derive from plan after step-1 green: green outcome survives."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from build_ledger import Ledger
    led = Ledger.from_plan("KLC-T2")
    led.mark("step-1", "green", model="m")
    led.save()

    led2 = Ledger.from_plan("KLC-T2")   # re-derive (plan may have been edited)
    assert led2.steps[0].state == "green"
    assert led2.first_pending() == 2


def test_ledger_all_green_returns_none(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from build_ledger import Ledger
    led = Ledger.from_plan("KLC-T2")
    led.mark("step-1", "green", model="m")
    led.mark("step-2", "green", model="m")
    assert led.first_pending() is None


def test_ledger_load_returns_none_when_absent(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from build_ledger import Ledger
    assert Ledger.load("KLC-T2") is None


def test_ledger_malformed_raises(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from build_ledger import Ledger
    build_dir = ticket_dir / ".klc" / "tickets" / "KLC-T2" / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "progress.md").write_text("not-yaml-frontmatter\n")
    with pytest.raises(ValueError):
        Ledger.load("KLC-T2")


def test_ledger_load_converts_running_to_pending(ticket_dir, monkeypatch):
    """Crash recovery: a step with state running is reset to pending on load."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from build_ledger import Ledger
    build_dir = ticket_dir / ".klc" / "tickets" / "KLC-T2" / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "progress.md").write_text(
        "---\nticket: KLC-T2\nsteps:\n"
        "  - id: step-1\n    state: running\n    model: m\n"
        "  - id: step-2\n    state: pending\n"
        "---\n# Build progress — KLC-T2\n"
    )
    led = Ledger.load("KLC-T2")
    assert led.steps[0].state == "pending"  # running → pending
    assert led.steps[1].state == "pending"


# ---------------------------------------------------------------------------
# step-2 tests: orchestrator dispatch loop
# ---------------------------------------------------------------------------

def test_orchestrator_dispatches_each_pending_step(ticket_dir, monkeypatch):
    """Stub dispatch is called once per step in order; ledger ends all-green."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))

    calls = []

    def stub_dispatch(phase_id, prompt_path, out_path, *, track=None):
        calls.append((phase_id, str(prompt_path), str(out_path)))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\ngreen\n", encoding="utf-8")
        return 0

    from build_orchestrator import run_build
    rc = run_build("KLC-T2", dispatch=stub_dispatch)

    assert rc == 0
    assert len(calls) == 2
    assert "step-1" in calls[0][1]
    assert "step-2" in calls[1][1]

    from build_ledger import Ledger
    led = Ledger.load("KLC-T2")
    assert led.steps[0].state == "green"
    assert led.steps[1].state == "green"


def test_model_note_printed_on_fallback(ticket_dir, monkeypatch, capsys):
    """MODEL_NOTE is printed when check_subagent_dispatch returns a note string."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))

    def stub_dispatch(phase_id, prompt_path, out_path, *, track=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\ngreen\n", encoding="utf-8")
        return 0

    import build_orchestrator as _bo
    monkeypatch.setattr(_bo, "check_subagent_dispatch", lambda resolved: "MODEL_NOTE fallback test")

    from build_orchestrator import run_build
    run_build("KLC-T2", dispatch=stub_dispatch)

    captured = capsys.readouterr()
    assert "MODEL_NOTE" in captured.out


# ---------------------------------------------------------------------------
# step-3 tests: resume + blocked semantics
# ---------------------------------------------------------------------------

def test_resume_skips_completed_steps(ticket_dir, monkeypatch):
    """Seed step-1 green in ledger; run_build dispatches only step-2."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))

    from build_ledger import Ledger
    led = Ledger.from_plan("KLC-T2")
    led.mark("step-1", "green", model="m")
    led.save()

    calls = []

    def stub_dispatch(phase_id, prompt_path, out_path, *, track=None):
        calls.append(str(prompt_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\ngreen\n", encoding="utf-8")
        return 0

    from build_orchestrator import run_build
    rc = run_build("KLC-T2", dispatch=stub_dispatch)

    assert rc == 0
    assert len(calls) == 1
    assert "step-2" in calls[0]


def test_blocked_step_halts_and_is_resumable(ticket_dir, monkeypatch):
    """Stub returns non-zero for step-1 → step-1 blocked, step-2 never dispatched.
    Second run re-dispatches step-1 because first_pending() returns steps where
    state != green, including blocked.
    """
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))

    call_log = []

    def failing_dispatch(phase_id, prompt_path, out_path, *, track=None):
        call_log.append(("fail", str(prompt_path)))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\nerror\n", encoding="utf-8")
        return 1

    from build_orchestrator import run_build
    rc = run_build("KLC-T2", dispatch=failing_dispatch)

    assert rc != 0
    assert len(call_log) == 1
    assert "step-1" in call_log[0][1]

    from build_ledger import Ledger
    led = Ledger.load("KLC-T2")
    assert led.steps[0].state == "blocked"
    assert led.steps[0].reason == "dispatch rc=1"
    assert led.steps[1].state == "pending"

    # Second run re-dispatches the blocked step (treated as pending)
    call_log.clear()

    def success_dispatch(phase_id, prompt_path, out_path, *, track=None):
        call_log.append(("ok", str(prompt_path)))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\ngreen\n", encoding="utf-8")
        return 0

    rc2 = run_build("KLC-T2", dispatch=success_dispatch)
    assert rc2 == 0
    assert len(call_log) == 2  # step-1 retried + step-2


# ---------------------------------------------------------------------------
# step-4 tests: build-run verb + CLI handler
# ---------------------------------------------------------------------------

def test_build_run_verb_registered():
    text = (Path(_FW_ROOT) / "scripts" / "klc").read_text()
    assert '"build-run"' in text or "'build-run'" in text


def test_build_run_appends_progress_and_returns_zero(ticket_dir, monkeypatch):
    """CLI via core/phases/build_run runs orchestrator; progress.md shows green."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))

    import importlib, sys as _sys
    for mod in list(_sys.modules.keys()):
        if "build_run" in mod or "build_orchestrator" in mod or "build_ledger" in mod:
            del _sys.modules[mod]

    def _stub_run_build(ticket, *, dispatch=None):
        from build_ledger import Ledger
        led = Ledger.from_plan(ticket)
        for s in led.steps:
            led.mark(s.id, "green", model="m")
        led.save()
        return 0

    import unittest.mock as _mock
    with _mock.patch.dict(_sys.modules, {}):
        import build_orchestrator as _bo
        with _mock.patch.object(_bo, "run_build", side_effect=_stub_run_build):
            from core.phases import build_run as br_phase
            importlib.reload(br_phase)
            rc = br_phase.run(["KLC-T2"])

    assert rc == 0
    from build_ledger import Ledger
    led = Ledger.load("KLC-T2")
    assert led is not None
    assert all(s.state == "green" for s in led.steps)
