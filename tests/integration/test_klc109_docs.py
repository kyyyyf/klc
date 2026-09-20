"""tests/integration/test_klc109_docs.py — KLC-109 step-3, AC-14: docs/process.md
states the fix-don't-waive rule with the KLC-109 ordering-gate example.
"""
from __future__ import annotations

from pathlib import Path

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "process.md"


def test_process_doc_states_fix_dont_waive_rule_with_klc109_example():
    """AC-14: docs/process.md's Build "Completion criteria" area (the passage
    that already names core/skills/tdd_order.py) states that a misfiring gate
    is fixed in the framework and never waived per project, names KLC-109 as
    the worked example, and names core/skills/test_conventions.py as the
    extension point for a new language layout."""
    text = _DOCS.read_text(encoding="utf-8")
    assert "fixed in the framework" in text
    assert "never waived per project" in text
    assert "KLC-109" in text
    assert "core/skills/test_conventions.py" in text
    # The rule must live in the SAME section that already names tdd_order.py
    # (the Build phase's Completion criteria), not just anywhere in the doc.
    tdd_order_idx = text.index("core/skills/tdd_order.py")
    rule_idx = text.index("fixed in the framework")
    assert abs(rule_idx - tdd_order_idx) < 4000, (
        "the fix-don't-waive rule must sit near the tdd_order.py gate description")
