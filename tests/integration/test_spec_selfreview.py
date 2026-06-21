"""Tests for core/skills/spec_selfreview.py (KLC-033 step-1).

RED test: both tests fail until spec_selfreview.py is created and
prompt_harness.py imports PLACEHOLDER_TOKENS from it.
"""
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))

import core.skills.spec_selfreview as spec_selfreview  # noqa: E402
from core.skills.spec_selfreview import scan_spec  # noqa: E402
import tests.prompt_harness as prompt_harness  # noqa: E402

_DIRTY_SPEC = """\
# Test spec

## Acceptance Criteria
- [ ] AC-1

[!CONFLICT C-001] unresolved
TODO: fill in
"""

_CLEAN_SPEC = """\
# Test spec

## Acceptance Criteria
- [ ] AC-1: The system does X when Y is present.
- [ ] AC-2: Error handling works correctly.
"""


def test_scan_detects_each_class():
    violations = scan_spec(_DIRTY_SPEC)
    classes = {v["class"] for v in violations}
    assert "placeholder" in classes, f"expected placeholder violation, got {violations}"
    assert "conflict" in classes, f"expected conflict violation, got {violations}"
    assert "stub_ac" in classes, f"expected stub_ac violation, got {violations}"
    assert scan_spec(_CLEAN_SPEC) == []


def test_harness_imports_canonical_tokens():
    assert prompt_harness.PLACEHOLDER_TOKENS is spec_selfreview.PLACEHOLDER_TOKENS
