"""Tests for core.skills.impl_plan_check (KLC-036 step-1).

Verifies the shared scanner is importable from core.skills and that
tests/prompt_harness.py re-exports are intact (no drift between the two).
"""
from core.skills.impl_plan_check import (
    impl_plan_violations,
    parse_impl_plan_steps,
    REQUIRED_STEP_FIELDS,
)
import tests.prompt_harness as H

_FULL_STEP = (
    "## step-1 — do something\n"
    "**Goal:** implement the feature\n"
    "**RED:** not applicable — config-only change\n"
    "**GREEN:** update the config file\n"
    "**VERIFY:** `pytest tests/ -q`\n"
    "**Expected:** 1 passed\n"
    "**COMMIT:** `KLC-000 step-1: do something`\n"
    "**Affected:** some/module.py\n"
    "**Interfaces:** none — no new signatures\n"
    "**Depends-on:** none\n"
)

_INCOMPLETE_STEP = (
    "## step-1 — implement x\n"
    "**Goal:** add helper\n"
    "**VERIFY:** `pytest tests/ -q`\n"
    "**COMMIT:** `KLC-000 step-1: add helper`\n"
    "**Affected:** module.py\n"
)


def test_import_from_core_skills():
    assert callable(impl_plan_violations)
    assert callable(parse_impl_plan_steps)
    assert isinstance(REQUIRED_STEP_FIELDS, tuple)


def test_harness_reexports_same_symbols():
    """prompt_harness must re-export the same objects (not copies)."""
    assert H.impl_plan_violations is impl_plan_violations
    assert H.parse_impl_plan_steps is parse_impl_plan_steps
    assert H.REQUIRED_STEP_FIELDS is REQUIRED_STEP_FIELDS


def test_full_step_clean():
    assert impl_plan_violations(_FULL_STEP) == []


def test_incomplete_step_violations():
    vs = impl_plan_violations(_INCOMPLETE_STEP)
    assert any("Interfaces" in v for v in vs)
    assert any("Expected" in v for v in vs)
    assert any("Code sketch" in v for v in vs)


def test_no_steps_violation():
    vs = impl_plan_violations("just prose, no step headings")
    assert any("no steps" in v for v in vs)


def test_parse_steps_returns_list():
    steps = parse_impl_plan_steps(_FULL_STEP)
    assert len(steps) == 1
    assert steps[0]["id"] == "step-1"
