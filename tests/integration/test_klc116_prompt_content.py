#!/usr/bin/env python3
"""KLC-116 step-7 — AC-12: the design, discovery, discovery-lite and
impl-plan-reviewer prompts instruct that a runtime-behaviour premise must be
`observed`, with the probe run during design rather than deferred to the
manual phase. The instruction is single-sourced in two shared includes — an
author-voice one for the three authoring prompts, and a reviewer-voice one
(F-3/D-203) for `impl-plan-reviewer.md`, which does not author items itself.

Every row greps the INCLUDE-EXPANDED text (`plugin_gen.expand_includes`),
because that is what the deployed prompt actually contains (design D-009) —
a raw grep of the source would only find the `{{include:...}}` directive.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import plugin_gen  # noqa: E402

AGENTS = FW_ROOT / "core" / "agents"


def _expanded(name: str) -> str:
    return plugin_gen.expand_includes((AGENTS / name).read_text(encoding="utf-8"))


def test_design_prompt_instructs_observed_during_design():
    text = _expanded("design.md")
    assert "must be `observed`" in text
    assert "during design" in text


def test_discovery_prompt_instructs_observed_during_design():
    text = _expanded("discovery.md")
    assert "must be `observed`" in text
    assert "during design" in text


def test_discovery_lite_prompt_instructs_observed_during_design():
    text = _expanded("discovery-lite.md")
    assert "must be `observed`" in text
    assert "during design" in text


def test_prompt_content_test_fails_when_instruction_is_removed():
    """Anti-vacuity for the author-voice include: strip the clause from an
    in-memory copy and confirm the assertion this file makes would fail."""
    text = _expanded("design.md")
    assert "must be `observed`" in text
    stripped = text.replace("must be `observed`", "")
    assert "must be `observed`" not in stripped


def test_impl_plan_reviewer_prompt_carries_the_reviewer_clause():
    """F-3/D-203: the reviewer gets its OWN clause — verify the declared label,
    verify an `observed` item's probe, and raise a finding on an unmeasured
    load-bearing claim — not the author-voice instruction it cannot act on."""
    text = _expanded("impl-plan-reviewer.md")
    assert "Verify every load-bearing DECISION declares `evidence=`" in text
    assert "Raise a finding when a load-bearing" in text


def test_impl_plan_reviewer_prompt_also_states_the_runtime_behaviour_standard():
    """AC-12's own wording still has to hold for all four prompts."""
    text = _expanded("impl-plan-reviewer.md")
    assert "must be `observed`" in text
    assert "during design" in text


def test_reviewer_clause_test_fails_when_the_clause_is_removed():
    """Anti-vacuity for the reviewer-voice include."""
    text = _expanded("impl-plan-reviewer.md")
    clause = "Verify every load-bearing DECISION declares `evidence=`"
    assert clause in text
    stripped = text.replace(clause, "")
    assert clause not in stripped
