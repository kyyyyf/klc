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


# ---------------------------------------------------------------------------
# KLC-050 step-4: unified parser + template retirement
# ---------------------------------------------------------------------------

import sys
from pathlib import Path
from unittest.mock import patch

_FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

_SAMPLE_PLAN = (
    "## step-1 — first\n"
    "**Goal:** do first\n"
    "**RED:** not applicable\n"
    "**VERIFY:** pytest\n"
    "**Expected:** 1 passed\n"
    "**COMMIT:** KLC-000 step-1: first\n"
    "**Affected:** a.py\n"
    "**Interfaces:** none\n"
    "**Depends-on:** none\n"
    "**Code sketch:**\n```python\npass\n```\n"
    "## step-2 — second\n"
    "**Goal:** do second\n"
    "**RED:** add test_second fails first\n"
    "**VERIFY:** pytest\n"
    "**Expected:** 1 passed\n"
    "**COMMIT:** KLC-000 step-2: second\n"
    "**Affected:** b.py\n"
    "**Interfaces:** none\n"
    "**Depends-on:** step-1\n"
    "**Code sketch:**\n```python\npass\n```\n"
)


def test_single_step_parser_delegates(tmp_path):
    """phase_completion._impl_plan_steps must delegate to parse_impl_plan_steps (unified parser)."""
    # bare import mirrors what phase_completion uses; both resolve to sys.modules["impl_plan_check"]
    import impl_plan_check as _ipc
    from core.skills import phase_completion
    (tmp_path / "impl-plan.md").write_text(_SAMPLE_PLAN)

    with patch.object(_ipc, "parse_impl_plan_steps",
                      wraps=_ipc.parse_impl_plan_steps) as spy:
        result = phase_completion._impl_plan_steps(tmp_path)
        spy.assert_called_once()

    assert len(result) == 2
    assert result[0] == {"step": 1, "red_not_applicable": True}
    assert result[1] == {"step": 2, "red_not_applicable": False}


# ---------------------------------------------------------------------------
# KLC-075 defect-3: impl_plan_check must tolerate the `**RED**:` emphasis form
# identically to phase_completion (asterisks BETWEEN `RED` and the colon).
# ---------------------------------------------------------------------------

_NA_EMPHASIS_STEP = (
    "## step-1 — prompt-only change\n"
    "**Goal:** update the agent prompt\n"
    "**RED**: not applicable — prompt/doc change\n"  # asterisks BEFORE the colon
    "**GREEN:** edit the prompt\n"
    "**VERIFY:** `pytest tests/ -q`\n"
    "**Expected:** 1 passed\n"
    "**COMMIT:** `KLC-000 step-1: prompt`\n"
    "**Affected:** core/agents/x.md\n"
    "**Interfaces:** none — no new signatures\n"
    "**Depends-on:** none\n"
)


def test_red_emphasis_form_exempts_code_sketch():
    """`**RED**: not applicable` (asterisks before the colon) must exempt the
    code-sketch requirement, matching phase_completion's tolerant parser."""
    vs = impl_plan_violations(_NA_EMPHASIS_STEP)
    assert not any("code sketch" in v.lower() for v in vs), vs


def test_red_plain_and_wrapped_forms_still_exempt():
    """The pre-existing `RED: not applicable` and `**RED:** not applicable`
    forms must keep exempting the code sketch (no regression)."""
    plain = _NA_EMPHASIS_STEP.replace(
        "**RED**: not applicable", "RED: not applicable")
    wrapped = _NA_EMPHASIS_STEP.replace(
        "**RED**: not applicable", "**RED:** not applicable")
    for text in (plain, wrapped):
        vs = impl_plan_violations(text)
        assert not any("code sketch" in v.lower() for v in vs), (text, vs)


# KLC-075 FIX-5: the exemption must mirror phase_completion's STRUCTURE — inspect
# only the FIRST `RED:` line, not the whole body. A step with a GENUINE RED plus
# an unrelated prose line that coincidentally reads "red: ... not applicable"
# must NOT be exempted.
_COINCIDENTAL_RED_PROSE_STEP = (
    "## step-1 — real behaviour work\n"
    "**Goal:** add the widget colour toggle\n"
    "**RED:** add test_widget_turns_red failing first\n"  # GENUINE red — needs code
    "**GREEN:** implement the toggle\n"
    "**VERIFY:** `pytest tests/ -q`\n"
    "**Expected:** 1 passed\n"
    "**COMMIT:** `KLC-000 step-1: widget`\n"
    "**Affected:** widget.py\n"
    "**Interfaces:** none — no new signatures\n"
    "**Notes:** the widget turns red: not applicable when disabled\n"  # coincidental prose
    # deliberately NO code-sketch fence
)


def test_coincidental_red_prose_not_exempted():
    """A genuine-RED step must still require a code sketch even when an unrelated
    prose line happens to contain 'red: ... not applicable' — the exemption only
    inspects the first `RED:` line (mirrors phase_completion)."""
    vs = impl_plan_violations(_COINCIDENTAL_RED_PROSE_STEP)
    assert any("code sketch" in v.lower() for v in vs), vs


def test_plan_template_renders_gate_passing():
    """Any remaining impl-plan template must render a gate-passing skeleton."""
    templates_dir = _FW_ROOT / "core" / "templates"
    stale = list(templates_dir.glob("impl-plan*.j2"))
    assert stale == [], (
        f"Stale templates must be removed (AC-5): {[p.name for p in stale]}"
    )
