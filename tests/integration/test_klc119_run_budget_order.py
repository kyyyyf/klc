#!/usr/bin/env python3
"""KLC-119 step-5 — AC-9 (D-203): `/klc:run`'s advisory budget check
consumes the dispatch card's own logged estimate — the card renders before
the gate, and a missing estimate fails closed rather than reading as zero.
The XS inline fast-track branch survives the reorder untouched.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import budget_guard  # noqa: E402

SKILL = FW_ROOT / "klc-plugin" / "skills" / "run" / "SKILL.md"


def test_run_skill_renders_card_before_budget_check_and_hard_breach_over_m_limit_stops_without_dispatch():
    text = SKILL.read_text(encoding="utf-8")
    render_pos = text.index("render_card")
    gate_pos = text.index("gate_card_dispatch")
    task_pos = text.index("Task(subagent_type=")
    assert render_pos < gate_pos < task_pos, \
        "the card must render, then the gate consumes it, before Task() dispatches"

    # M's hard limit is 90000 est. tokens (config/budgets.yml) — a card sized
    # over it stops the loop without dispatching.
    verdict = budget_guard.gate_card_dispatch("M", 90_001)
    assert verdict.hard_breach is True


def test_missing_or_unrenderable_card_estimate_fails_closed_rather_than_permitting_dispatch():
    verdict = budget_guard.gate_card_dispatch("M", None)
    assert verdict.hard_breach is True, \
        "a missing estimate must be a hard breach, never treated as zero"
    assert verdict.soft_breach is True
    assert verdict.estimated != 0


def test_runs_inline_branch_survives_the_reorder_and_never_reaches_task_dispatch():
    text = SKILL.read_text(encoding="utf-8")
    assert re.search(r"b\. If `resolved\.runs_inline`", text), \
        "the XS fast-track branch must stay verbatim at letter b (D-203)"
    inline_pos = text.index("If `resolved.runs_inline` (XS fast-track)")
    task_pos = text.index("Task(subagent_type=")
    assert inline_pos < task_pos, \
        "the inline branch must be reachable before the Task() dispatch text"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
