#!/usr/bin/env python3
"""tests/test_budget_guard.py — KLC-052 step-2: budget_guard extraction.

check_prompt_budget(track, estimated) is the advisory (non-dispatching)
counterpart of runner.py's inline hard/soft-limit guard, so the
orchestrator can decide whether to even attempt a dispatch.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import budget_guard  # noqa: E402


def test_hard_breach_is_flagged():
    with patch.object(budget_guard, "load_budget_limits",
                       return_value=({"XS": 100}, {"XS": 200})):
        verdict = budget_guard.check_prompt_budget("XS", 250)
    assert verdict.hard_breach is True
    print("PASS: hard breach is flagged")


def test_soft_breach_warns_not_blocks():
    with patch.object(budget_guard, "load_budget_limits",
                       return_value=({"XS": 100}, {"XS": 200})):
        verdict = budget_guard.check_prompt_budget("XS", 150)
    assert verdict.hard_breach is False
    assert verdict.soft_breach is True
    print("PASS: soft breach warns, does not block")


if __name__ == "__main__":
    test_hard_breach_is_flagged()
    test_soft_breach_warns_not_blocks()
