"""KLC-042 / KLC-174: build orchestrator — dispatch loop on step_state, resume, CLI verb."""
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
sys.path.insert(0, str(_FW_ROOT / "tests"))

import klc114_helpers as h  # noqa: E402

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
    "track": "XS",   # XS: per-step review skipped; these tests focus on dispatch loop only
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


@pytest.fixture()
def fake(monkeypatch):
    """KLC-174: this suite exercises the DISPATCH LOOP, not git-derived state. Its
    fake dispatches write a report and never commit, so the real `step_state`
    would call every step pending. `FakeStepState` stands in for derive/record."""
    return h.pin_step_state(monkeypatch, [1, 2])


def _ok(calls=None):
    def stub_dispatch(phase_id, prompt_path, out_path, *, inputs=None, track=None):
        if calls is not None:
            calls.append(str((inputs or {}).get("brief", prompt_path)))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\ngreen\n", encoding="utf-8")
        return 0
    return stub_dispatch


def test_orchestrator_dispatches_each_pending_step(ticket_dir, monkeypatch, fake):
    """Dispatch is called once per step in order; each step is green via record_verify."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    calls = []
    from build_orchestrator import run_build
    rc = run_build("KLC-T2", dispatch=_ok(calls))

    assert rc == 0
    assert len(calls) == 2
    assert "step-1" in calls[0]
    assert "step-2" in calls[1]
    assert fake.recorded == [1, 2]
    assert fake.green == {1, 2}


def test_no_progress_ledger_is_written(ticket_dir, monkeypatch, fake):
    """KLC-174: progress is derived; build/progress.md is no longer written."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from build_orchestrator import run_build
    assert run_build("KLC-T2", dispatch=_ok()) == 0
    build_dir = ticket_dir / ".klc" / "tickets" / "KLC-T2" / "build"
    assert not (build_dir / "progress.md").exists()


def test_model_note_printed_on_fallback(ticket_dir, monkeypatch, capsys, fake):
    """MODEL_NOTE is printed when check_subagent_dispatch returns a note string."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    import build_orchestrator as _bo
    monkeypatch.setattr(_bo, "check_subagent_dispatch", lambda resolved: "MODEL_NOTE fallback test")
    _bo.run_build("KLC-T2", dispatch=_ok())
    assert "MODEL_NOTE" in capsys.readouterr().out


def test_resume_skips_completed_steps(ticket_dir, monkeypatch):
    """step-1 already green in step_state; run_build dispatches only step-2."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    fk = h.pin_step_state(monkeypatch, [1, 2], green={1})
    calls = []
    from build_orchestrator import run_build
    assert run_build("KLC-T2", dispatch=_ok(calls)) == 0
    assert len(calls) == 1
    assert "step-2" in calls[0]
    assert fk.recorded == [2]


def test_blocked_step_halts_and_is_resumable(ticket_dir, monkeypatch, fake):
    """A failing dispatch halts the build, records no verify, and the next run
    re-dispatches the same step (it is simply not green)."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    call_log = []

    def failing_dispatch(phase_id, prompt_path, out_path, *, inputs=None, track=None):
        call_log.append(str((inputs or {}).get("brief", prompt_path)))
        return 1

    from build_orchestrator import run_build
    assert run_build("KLC-T2", dispatch=failing_dispatch) == 1
    assert len(call_log) == 1 and "step-1" in call_log[0]
    assert fake.recorded == []
    assert fake.green == set()

    calls = []
    assert run_build("KLC-T2", dispatch=_ok(calls)) == 0
    assert len(calls) == 2  # step-1 retried + step-2


def test_not_green_after_verify_halts_without_dispatching_next(ticket_dir, monkeypatch):
    """A dispatch that returns 0 is NOT enough: a step whose recorded verify fails
    keeps the build blocked and step-2 is never dispatched."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    fk = h.pin_step_state(monkeypatch, [1, 2], fail={1})
    calls = []
    from build_orchestrator import run_build
    assert run_build("KLC-T2", dispatch=_ok(calls)) == 1
    assert len(calls) == 1 and "step-1" in calls[0]
    assert fk.recorded == [1]


def test_empty_plan_is_not_a_finished_build(tmp_path, monkeypatch, capsys):
    """KLC-174: an impl-plan with no steps is not 'all green' — build-run fails."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc" / "tickets" / "KLC-T2"
    tdir.mkdir(parents=True)
    (tdir / "impl-plan.md").write_text("# nothing\n")
    (tdir / "meta.json").write_text(_META)
    from build_orchestrator import run_build
    assert run_build("KLC-T2", dispatch=_ok()) == 1
    assert "no steps" in capsys.readouterr().err


def test_real_step_state_decides_green(tmp_path, monkeypatch):
    """No fakes: a dispatch that makes the red then green commit, with an
    allowlisted VERIFY, ends green only because step_state recorded and derived it."""
    import json as _json
    import subprocess
    repo = h.make_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PROJECT_ROOT", str(repo))
    plan = _PLAN.split("## step-2")[0].replace("**VERIFY:** pytest",
                                              "**VERIFY:** `python3 -m pytest tests/test_first.py -q`")
    tdir = repo / ".klc" / "tickets" / "KLC-T2"
    tdir.mkdir(parents=True)
    (tdir / "impl-plan.md").write_text(plan)
    (tdir / "spec.md").write_text(_SPEC)
    (tdir / "meta.json").write_text(_META)

    def dispatch(phase_id, prompt_path, out_path, *, inputs=None, track=None):
        h.commit(repo, {"tests/test_first.py": "def test_a():\n    assert True\n"},
                 "KLC-T2 step-1: add failing tests")
        h.commit(repo, {"src/first.py": "def first(): pass\n"}, "KLC-T2 step-1: first step")
        return 0

    from build_orchestrator import run_build
    import step_state
    assert run_build("KLC-T2", dispatch=dispatch) == 0
    recs = step_state.derive("KLC-T2")
    assert [r["state"] for r in recs] == ["green"]
    steps_json = _json.loads((tdir / "build" / "steps.json").read_text())
    assert steps_json["steps"]["1"]["verify"]["exit_code"] == 0
    assert not (tdir / "build" / "progress.md").exists()


# ---------------------------------------------------------------------------
# build-run verb + CLI handler
# ---------------------------------------------------------------------------

def test_build_run_verb_registered():
    text = (Path(_FW_ROOT) / "scripts" / "klc").read_text()
    assert '"build-run"' in text or "'build-run'" in text


def test_build_run_cli_returns_orchestrator_rc(ticket_dir, monkeypatch):
    """CLI via core/phases/build_run delegates to the orchestrator and returns its rc."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    import build_orchestrator as _bo
    from core.phases import build_run as br_phase
    with patch.object(_bo, "run_build", return_value=0) as rb:
        assert br_phase.run(["KLC-T2"]) == 0
    rb.assert_called_once_with("KLC-T2")
    with patch.object(_bo, "run_build", return_value=1):
        assert br_phase.run(["KLC-T2"]) == 1
