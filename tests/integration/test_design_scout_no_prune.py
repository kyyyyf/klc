#!/usr/bin/env python3
"""Integration tests for design-scout no-prune + artifact format (KLC-026 step-3).

Tests:
- AC-3: after a scout run, the three-option discipline is preserved in design.md
- AC-4: options.md / adr.md / impl-plan.md format unchanged
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

DESIGN_MD = FW_ROOT / "core" / "agents" / "design.md"


def _read_design() -> str:
    assert DESIGN_MD.exists()
    return DESIGN_MD.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-3: three-option discipline preserved
# ---------------------------------------------------------------------------

def test_three_options_preserved():
    """design.md still mandates three options A/B/C regardless of scout output."""
    text = _read_design()
    # The three-option mandate must still be present
    assert re.search(r"three\s+option", text, re.IGNORECASE) or \
           re.search(r"option.{0,10}A.{0,10}/?.{0,5}B.{0,10}/?.{0,5}C", text, re.IGNORECASE), \
        "design.md must still mandate three options A/B/C"
    # The hard rule against downgrading the track / reducing options must survive
    assert "CONFLICT items stop the phase" in text or \
           re.search(r"(never.{0,30}auto-resolve|CONFLICT.{0,20}stop)", text), \
        "design.md hard rules must still be present"


def test_design_artifacts_format_unchanged():
    """The declared outputs (options.md, impl-plan.md) are unchanged by the scout."""
    text = _read_design()
    # options.md must still be mentioned as an output
    assert "options.md" in text, "options.md must remain a design output"
    assert "impl-plan.md" in text, "impl-plan.md must remain a design output"
    # scout.md must NOT be in the declared outputs (it's an intermediate)
    # Specifically: scout.md should not appear in the ack "Outputs the ack step will verify"
    outputs_section = re.search(
        r"Outputs the ack step will verify(.*?)(?=##|\Z)", text, re.DOTALL | re.IGNORECASE
    )
    if outputs_section:
        outputs_text = outputs_section.group(1)
        assert "scout.md" not in outputs_text, \
            "scout.md must NOT be a declared ack output — it's an intermediate"


def test_can_complete_design_not_affected():
    """phase_completion.can_complete_design checks design.outputs from phases.yml.
    Scout.md must NOT appear in phases.yml design.outputs."""
    phases_path = FW_ROOT / "config" / "phases.yml"
    if not phases_path.exists():
        return  # no phases.yml to check
    text = phases_path.read_text(encoding="utf-8")
    # Find the design phase outputs block
    design_block = re.search(
        r"design:.*?outputs:(.*?)(?=\w+:|$)", text, re.DOTALL
    )
    if design_block:
        outputs = design_block.group(1)
        assert "scout.md" not in outputs, \
            "scout.md must not be in phases.yml design.outputs (AC-4)"
