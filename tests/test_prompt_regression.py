from tests.prompt_harness import impl_plan_violations, has_min_approaches
from pathlib import Path
import pytest
import tests.prompt_harness as H

GOOD = (
    "## step-1 — x\n"
    "**Goal:** do the thing\n"
    "**RED:** not applicable — prompt-only edit\n"
    "**GREEN:** update the prompt text\n"
    "**VERIFY:** `pytest tests/ -q`\n"
    "**Expected:** 1 passed\n"
    "**COMMIT:** `KLC-029 step-1: do the thing`\n"
    "**Affected:** tests/prompt_harness.py\n"
    "**Interfaces:** none — no new signatures\n"
    "**Depends-on:** none\n"
)
BAD = "## step-1 — x\n**Goal:** TODO\n"


def test_impl_plan_violations_flags_placeholders():
    assert impl_plan_violations(GOOD) == []
    assert impl_plan_violations(BAD)        # non-empty


def test_has_min_approaches_counts():
    assert has_min_approaches("- Option A: x\n- Option B: y", 2)
    assert not has_min_approaches("- Option A: x", 2)


def test_has_min_approaches_no_duplicate_label():
    # "Option A" repeated with different descriptions must NOT count as 2
    assert not has_min_approaches("- Option A: first\n- Option A: repeated", 2)


def test_violations_missing_required_field():
    text = (
        "## step-1 — x\n"
        "**Goal:** do the thing\n"
        "**VERIFY:** `pytest`\n"
        # missing COMMIT and Affected
    )
    violations = impl_plan_violations(text)
    assert any("COMMIT" in v for v in violations)


def test_violations_placeholder_tbd():
    text = (
        "## step-1 — x\n"
        "**Goal:** TBD\n"
        "**VERIFY:** `pytest`\n"
        "**COMMIT:** `done`\n"
        "**Affected:** file.py\n"
    )
    violations = impl_plan_violations(text)
    assert violations


def test_violations_no_steps():
    text = "# just prose, no step headings\nsome text"
    violations = impl_plan_violations(text)
    assert any("no steps" in v for v in violations)


def test_has_min_approaches_not_prose():
    # Normal prose shouldn't be counted as approaches
    assert not has_min_approaches("We will implement this using clangd.", 2)


def test_judge_skips_without_key(monkeypatch):
    monkeypatch.delenv(H._judge_api_key_env(), raising=False)
    assert H.judge_available() is False


def test_judge_skips_gracefully_without_key(monkeypatch):
    """AC-2: judge() must skip (not fail) when API key is absent."""
    monkeypatch.delenv(H._judge_api_key_env(), raising=False)
    with pytest.raises(pytest.skip.Exception):
        H.judge("output", "rubric")


def test_judge_returns_structured(monkeypatch):
    def _fake_run(**kw):
        Path(kw["out_path"]).write_text("PASS: ok")
        return 0
    monkeypatch.setattr(H, "run_agent", _fake_run, raising=False)
    monkeypatch.setattr(H, "judge_available", lambda: True)
    r = H.judge("out", "rubric")
    assert r["pass"] is True and isinstance(r["reason"], str)


def test_discovery_lite_lacks_socratic_sentinel():
    from tests.prompt_harness import _FW_ROOT
    txt = (_FW_ROOT / "core/agents/discovery-lite.md").read_text(encoding="utf-8")
    low = txt.lower()
    assert "one question at a time" in low
    assert ("2-3 approaches" in low) or ("2–3 approaches" in low)


def test_discovery_prompts_have_socratic_step():
    """AC-1/AC-5 (KLC-032): both discovery prompts must have the Socratic protocol markers."""
    from tests.prompt_harness import _FW_ROOT
    for name in ("discovery-lite.md", "discovery.md"):
        txt = (_FW_ROOT / "core/agents" / name).read_text(encoding="utf-8")
        low = txt.lower()
        assert "one question at a time" in low, f"{name}: missing 'one question at a time'"
        assert "explore" in low, f"{name}: missing 'explore' (context-first step)"
        assert ("2-3 approaches" in low) or ("2–3 approaches" in low), (
            f"{name}: missing approach count"
        )


def test_impl_plan_requires_executable_fields():
    """AC-2/AC-3 (KLC-035): steps missing Interfaces/Expected/code sketch must be flagged."""
    old_style = (
        "## step-1 — implement the helper\n"
        "**Goal:** add the helper function\n"
        "**RED:** `tests/test_x.py::test_y` — failing today\n"
        "**GREEN:** add helper function in module.py\n"
        "**VERIFY:** `pytest tests/ -q`\n"
        "**COMMIT:** `KLC-035 step-1: add helper`\n"
        "**Affected:** tests/prompt_harness.py\n"
        # deliberately missing: Interfaces, Expected, code sketch
    )
    violations = impl_plan_violations(old_style)
    assert violations, "expected violations for step missing Interfaces/Expected/code sketch"
    assert any("Interfaces" in v for v in violations), f"violations={violations}"
    assert any("Expected" in v for v in violations), f"violations={violations}"
    assert any("Code sketch" in v for v in violations), f"violations={violations}"


def test_code_sketch_field_required_not_any_fence():
    """Codex review [HIGH]: a fenced output block in Expected must not satisfy code-sketch check."""
    step_with_expected_fence_only = (
        "## step-1 — implement x\n"
        "**Goal:** implement the helper\n"
        "**RED:** `tests/test_x.py::test_y` — fails today\n"
        "**GREEN:** add helper in module.py\n"
        "**VERIFY:** `pytest tests/ -q`\n"
        "**Expected:**\n"
        "```text\n"
        "1 passed\n"
        "```\n"
        "**COMMIT:** `KLC-000 step-1: add helper`\n"
        "**Affected:** module.py\n"
        "**Interfaces:** `def helper() -> None`\n"
        # has a fenced block (output) but no **Code sketch:** field
    )
    violations = impl_plan_violations(step_with_expected_fence_only)
    assert any("Code sketch" in v for v in violations), (
        f"expected 'Code sketch' violation when only Expected has a fence; got: {violations}"
    )


def test_legacy_step_flags_full_step_clean():
    """AC-3 (KLC-035): legacy step → violations non-empty; fully-populated step → violations empty."""
    legacy = (
        "## step-1 — do something\n"
        "**Goal:** implement the feature\n"
        "**VERIFY:** `pytest tests/ -q`\n"
        "**COMMIT:** `KLC-000 step-1: do something`\n"
        "**Affected:** some/module.py\n"
        # old contract: no Interfaces, Expected, or code sketch
    )
    full = (
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
    assert impl_plan_violations(legacy), "legacy step should have violations"
    assert impl_plan_violations(full) == [], "fully-populated step should have no violations"


def test_discovery_prompts_have_self_review_step():
    """AC-5 (KLC-033): both discovery prompts must have a self-review step."""
    from tests.prompt_harness import _FW_ROOT
    for name in ("discovery-lite.md", "discovery.md"):
        txt = (_FW_ROOT / "core/agents" / name).read_text(encoding="utf-8")
        assert "self-review" in txt.lower(), (
            f"{name}: missing self-review step before '## Signals to emit' (KLC-033 AC-5)"
        )


# ---------------------------------------------------------------------------
# KLC-037: planning agent impl-plan self-review
# ---------------------------------------------------------------------------

_DIRTY_PLAN_FIXTURE = (
    "## step-1 — implement helper\n"
    "**Goal:** TODO\n"
    "**VERIFY:** `pytest tests/ -q`\n"
    "**COMMIT:** `KLC-000 step-1: add helper`\n"
    "**Affected:** module.py\n"
    # missing: Interfaces, Expected, Code sketch; Goal is a placeholder
)

_PLANNING_SELF_REVIEW_RUBRIC = """\
The planning agent was given an impl-plan draft that contains a step with
a placeholder Goal ('TODO') and missing required fields (Interfaces, Expected,
Code sketch).  The agent must self-review and fix the plan before emitting it.

Pass if the final emitted impl-plan satisfies ALL of:
  1. impl_plan_violations() returns [] for the emitted plan.
  2. No step contains a bare placeholder token (TODO, TBD, <...>).
  3. Every step has Interfaces, Expected, and Code sketch fields.

Fail if the agent emits the dirty plan unchanged or partially fixed.
"""


def test_dirty_plan_fixture_has_violations():
    """Offline: the dirty fixture must trigger violations (confirms RED state)."""
    vs = impl_plan_violations(_DIRTY_PLAN_FIXTURE)
    assert vs, "dirty fixture must have violations"
    assert any("Goal" in v or "TODO" in v or "Interfaces" in v for v in vs), f"got: {vs}"


def test_planning_agent_self_reviews_impl_plan(monkeypatch):
    """AC-1/AC-2 (KLC-037): design agent must not emit a plan with violations.

    Requires ANTHROPIC_API_KEY; skips gracefully without it.
    """
    if not H.judge_available():
        pytest.skip(f"judge API key ({H._judge_api_key_env()}) not set")
    result = H.judge(_DIRTY_PLAN_FIXTURE, _PLANNING_SELF_REVIEW_RUBRIC)
    assert result["pass"], f"planning agent emitted a dirty plan: {result['reason']}"


def test_design_prompt_has_impl_plan_self_review():
    """AC-3 (KLC-037): design.md must instruct the agent to self-review impl-plan."""
    txt = (H._FW_ROOT / "core/agents/design.md").read_text(encoding="utf-8")
    assert "self-review" in txt.lower(), "design.md: missing impl-plan self-review step"
    assert "REQUIRED_STEP_FIELDS" in txt or "required fields" in txt.lower(), (
        "design.md: self-review step must cite the required field contract"
    )


def test_test_planner_prompt_has_impl_plan_self_review():
    """AC-3 (KLC-037): test-planner.md must instruct the agent to self-review impl-plan."""
    txt = (H._FW_ROOT / "core/agents/test-planner.md").read_text(encoding="utf-8")
    assert "self-review" in txt.lower(), "test-planner.md: missing impl-plan self-review step"
    assert "REQUIRED_STEP_FIELDS" in txt or "required fields" in txt.lower(), (
        "test-planner.md: self-review step must cite the required field contract"
    )


def test_discovery_lite_prompt_has_impl_plan_self_review():
    """Codex [HIGH] (KLC-037): discovery-lite.md must self-review impl-plan for S-track."""
    txt = (H._FW_ROOT / "core/agents/discovery-lite.md").read_text(encoding="utf-8")
    low = txt.lower()
    assert "required fields" in low or "REQUIRED_STEP_FIELDS" in txt, (
        "discovery-lite.md: S-track impl-plan self-review must cite required field contract"
    )
    assert "placeholder" in low, (
        "discovery-lite.md: S-track impl-plan self-review must cite placeholder tokens"
    )
