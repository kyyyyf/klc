#!/usr/bin/env python3
"""KLC-119 step-5 / KLC-174 step-5 (AC-8): `/klc:run` renders the dispatch
card before the dispatch, and its budget prose names the WARN-ONLY real-spend
check (never a blocking card-size gate). The XS inline fast-track branch
survives untouched.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
SKILL = FW_ROOT / "klc-plugin" / "skills" / "go" / "SKILL.md"


def test_run_skill_renders_card_then_warns_only_before_dispatch():
    text = SKILL.read_text(encoding="utf-8")
    render_pos = text.index("render_card")
    warn_pos = text.index("real_spend_warning")
    task_pos = text.index("Task(subagent_type=")
    assert render_pos < warn_pos < task_pos
    assert "gate_card_dispatch" not in text
    assert "hard_breach" not in text
    assert "warn" in text[warn_pos - 200: warn_pos + 600].lower()


def test_runs_inline_branch_survives_and_never_reaches_task_dispatch():
    text = SKILL.read_text(encoding="utf-8")
    assert re.search(r"d\. If `resolved\.runs_inline`", text)
    assert text.index("If `resolved.runs_inline` (XS)") < text.index(
        "Task(subagent_type=")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
