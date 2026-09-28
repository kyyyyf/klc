#!/usr/bin/env python3
"""Tests for KLC-130: model-ID refresh + learn phase routing (AC-1, AC-2).

`config/models.yml` must declare the model IDs the subagents actually
dispatch to today, and the `learn` phase must route through the `coding`
role instead of `local-simple` (two of three haiku-run retrospectives
edited ADRs against instructions and invented numbers).
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
import models as _m


def test_role_ids_match_actual_dispatch() -> None:
    """AC-1: heavy-reasoning/coding/external/defaults carry the new IDs;
    the two haiku roles (local-simple/local-coding) are unchanged."""
    mc = _m.load_models()
    assert mc.roles["heavy-reasoning"].model == "claude-opus-5-5"
    assert mc.roles["coding"].model == "claude-sonnet-5"
    assert mc.roles["external"].model == "claude-sonnet-5"
    assert mc.defaults.model == "claude-sonnet-5"
    assert mc.roles["local-simple"].model == "claude-haiku-4-5-20251001"
    assert mc.roles["local-coding"].model == "claude-haiku-4-5-20251001"


def test_learn_routes_to_coding() -> None:
    """AC-2: phase_roles.learn resolves to the coding role/model, not
    local-simple."""
    mc = _m.load_models()
    resolved = mc.resolve("learn")
    assert resolved.role == "coding"
    assert resolved.model == "claude-sonnet-5"
