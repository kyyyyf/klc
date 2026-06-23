"""KLC-041: task_brief dependency-aware step slicer tests."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

# ---------------------------------------------------------------------------
# Synthetic impl-plan fixture
# ---------------------------------------------------------------------------

_PLAN = textwrap.dedent("""\
    ---
    ticket: KLC-T1
    kind: impl-plan
    ---

    # KLC-T1 — test impl plan

    ## step-1 — foundation

    - **Goal:** build foo
    - **Interfaces:** `def foo() -> int`
    - **Expected:** foo returns 42
    - **VERIFY:** pytest
    - **COMMIT:** KLC-T1 step-1: build foo
    - **Affected:** src/foo.py
    - **Code sketch:**

    ```python
    def foo():
        return 42
    ```

    ## step-2 — unrelated

    - **Goal:** build bar (no connection to step-1 or step-3)
    - **Interfaces:** `def bar() -> str`
    - **Expected:** bar returns "x"
    - **VERIFY:** pytest
    - **COMMIT:** KLC-T1 step-2: build bar
    - **Affected:** src/bar.py
    - **Code sketch:**

    ```python
    def bar():
        return "x"
    ```

    ## step-3 — consumer

    - **Goal:** use foo from step-1
    - **Interfaces:** `def consumer() -> int`
    - **Expected:** consumer calls foo
    - **VERIFY:** pytest
    - **COMMIT:** KLC-T1 step-3: consumer
    - **Affected:** src/consumer.py
    - Depends-on: step-1
    - **Code sketch:**

    ```python
    from foo import foo
    def consumer():
        return foo()
    ```
""")

_SPEC = textwrap.dedent("""\
    ---
    ticket: KLC-T1
    kind: feature
    authority: human
    risk_tags: []
    ---

    ## Goals
    Test the task-brief slicer.

    ## Acceptance Criteria
    - [ ] AC-1: brief contains step body
    - [ ] AC-2: brief contains dep interfaces
""")


@pytest.fixture()
def ticket_dir(tmp_path):
    """Create a minimal synthetic ticket directory."""
    tdir = tmp_path / ".klc" / "tickets" / "KLC-T1"
    tdir.mkdir(parents=True)
    (tdir / "impl-plan.md").write_text(_PLAN)
    (tdir / "spec.md").write_text(_SPEC)
    (tdir / "meta.json").write_text('{"ticket":"KLC-T1","track":"S","kind":"feature","phase":"build:work"}')
    return tmp_path


# ---------------------------------------------------------------------------
# step-1 tests: dependency slicing
# ---------------------------------------------------------------------------

def test_brief_contains_target_step_body(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from task_brief import build_step_brief
    brief = build_step_brief("KLC-T1", 3)
    assert "use foo from step-1" in brief  # step-3 Goal


def test_brief_contains_dep_interfaces(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from task_brief import build_step_brief
    brief = build_step_brief("KLC-T1", 3)
    assert "def foo() -> int" in brief  # step-1 interface


def test_brief_contains_dep_commit(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from task_brief import build_step_brief
    brief = build_step_brief("KLC-T1", 3)
    assert "KLC-T1 step-1: build foo" in brief  # step-1 COMMIT


def test_brief_excludes_dep_body(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from task_brief import build_step_brief
    brief = build_step_brief("KLC-T1", 3)
    # Code sketch from step-1 must not bleed into the brief
    assert "return 42" not in brief


def test_brief_excludes_unrelated_step(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from task_brief import build_step_brief
    brief = build_step_brief("KLC-T1", 3)
    assert "build bar" not in brief       # step-2 Goal absent
    assert "def bar()" not in brief       # step-2 interface absent


def test_brief_no_deps_has_no_dep_section_content(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from task_brief import build_step_brief
    brief = build_step_brief("KLC-T1", 1)  # step-1 has no Depends-on
    assert "def bar()" not in brief
    assert "consumer" not in brief


def test_missing_step_raises(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from task_brief import build_step_brief
    with pytest.raises(ValueError, match="step-99"):
        build_step_brief("KLC-T1", 99)


def test_missing_plan_raises(tmp_path, monkeypatch):
    tdir = tmp_path / ".klc" / "tickets" / "KLC-NOPLAN"
    tdir.mkdir(parents=True)
    (tdir / "spec.md").write_text(_SPEC.replace("KLC-T1", "KLC-NOPLAN"))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from task_brief import build_step_brief
    with pytest.raises(ValueError, match="impl-plan"):
        build_step_brief("KLC-NOPLAN", 1)


# ---------------------------------------------------------------------------
# step-2 tests: template sections
# ---------------------------------------------------------------------------

def test_brief_sections_present(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from task_brief import build_step_brief
    brief = build_step_brief("KLC-T1", 3)
    assert "## Global constraints" in brief
    assert "## This step" in brief
    assert "## Depended-on interfaces" in brief


def test_brief_decisions_section_absent_when_no_decisions(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    from task_brief import build_step_brief
    brief = build_step_brief("KLC-T1", 3)
    assert "DECISION D-" not in brief


# ---------------------------------------------------------------------------
# step-3 tests: CLI verb + scaffold
# ---------------------------------------------------------------------------

def test_verb_registered():
    text = (Path(_FW_ROOT) / "scripts" / "klc").read_text()
    assert '"task-brief"' in text or "'task-brief'" in text


def test_cli_writes_brief_and_scaffold(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    import sys as _sys
    mod_name = "core.phases.task_brief"
    if mod_name in _sys.modules:
        del _sys.modules[mod_name]
    from core.phases import task_brief as tb_phase
    rc = tb_phase.run(["KLC-T1", "3"])
    assert rc == 0
    build = ticket_dir / ".klc" / "tickets" / "KLC-T1" / "build"
    assert (build / "step-3-brief.md").exists()
    assert (build / "step-3-impl-report.md").exists()


def test_out_of_range_step_errors(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    import sys as _sys
    mod_name = "core.phases.task_brief"
    if mod_name in _sys.modules:
        del _sys.modules[mod_name]
    from core.phases import task_brief as tb_phase
    rc = tb_phase.run(["KLC-T1", "99"])
    assert rc != 0
