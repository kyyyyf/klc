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
