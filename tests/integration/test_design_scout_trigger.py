#!/usr/bin/env python3
"""Integration tests for design-scout trigger wiring in design.md (KLC-026 step-3).

Tests:
- AC-1: scout runs on public_api_change trigger
- AC-1: scout runs when uncertainty >= 2
- AC-1: scout runs before options.md is authored
- AC-5: scout skipped when no trigger matches
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

DESIGN_MD = FW_ROOT / "core" / "agents" / "design.md"
DESIGN_SCOUT_MD = FW_ROOT / "core" / "agents" / "design-scout.md"


def _read_design() -> str:
    assert DESIGN_MD.exists(), f"design.md not found at {DESIGN_MD}"
    return DESIGN_MD.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-1: trigger conditions present in design.md
# ---------------------------------------------------------------------------

def test_runs_on_public_api_change():
    """design.md contains a scout trigger on public-API changes."""
    text = _read_design()
    # Must mention the scout running on public API changes
    assert re.search(r"public.{0,20}api.{0,30}(change|trigger|scout)", text, re.IGNORECASE), \
        "design.md does not wire the scout on public-API change trigger"


def test_runs_on_uncertainty_ge_2():
    """design.md contains a scout trigger when uncertainty >= 2."""
    text = _read_design()
    assert re.search(r"uncertainty\s*[>≥]=?\s*2", text, re.IGNORECASE) or \
           re.search(r"uncertainty.{0,30}(2|two).{0,30}(scout|trigger|run)", text, re.IGNORECASE), \
        "design.md does not wire the scout on uncertainty >= 2 trigger"


def test_runs_before_options():
    """The scout step appears before the option-generation step in design.md."""
    text = _read_design()
    # Find positions of scout mention and option generation
    scout_pos = re.search(r"scout", text, re.IGNORECASE)
    options_pos = re.search(r"##\s+Steps", text, re.IGNORECASE)
    # More specifically: scout step (Step 0) must precede the options generation
    step0_pos = re.search(r"step\s*0", text, re.IGNORECASE)
    step1_pos = re.search(r"###\s+1[^a].*[Gg]enerate\s+option", text, re.IGNORECASE)
    assert step0_pos is not None, "design.md has no Step 0 for the scout"
    assert step1_pos is not None, "design.md has no Step 1 option-generation step"
    assert step0_pos.start() < step1_pos.start(), \
        "Step 0 (scout) must appear before Step 1 (options) in design.md"


def test_skipped_when_no_trigger():
    """design.md explicitly describes the skip path when no trigger fires."""
    text = _read_design()
    # Must state that the scout is skipped / conditional
    has_skip = re.search(
        r"(skip|omit|proceed\s+without|no\s+trigger|when\s+neither).{0,80}scout",
        text, re.IGNORECASE,
    ) or re.search(
        r"scout.{0,80}(skip|omit|not\s+triggered|proceed\s+as\s+today)",
        text, re.IGNORECASE,
    )
    assert has_skip, "design.md must describe the scout-skipped path (AC-5)"
