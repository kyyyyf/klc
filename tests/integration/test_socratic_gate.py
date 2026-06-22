"""Tests for core/skills/spec_structure.py helpers (KLC-032 step-1)."""
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))  # for bare imports inside phase_completion

from core.skills import spec_structure  # noqa: E402
import tests.prompt_harness as prompt_harness  # noqa: E402


def test_helpers_importable_and_shared():
    """has_min_approaches re-exported from harness must be the same object as spec_structure's."""
    assert prompt_harness.has_min_approaches is spec_structure.has_min_approaches


def test_recorded_pick_detects_picked_marker():
    assert spec_structure.recorded_pick("Picked: Option A — lower coupling")


def test_recorded_pick_detects_decision_marker():
    assert spec_structure.recorded_pick("DECISION D-001: use clangd backend")


def test_recorded_pick_rejects_prose():
    assert not spec_structure.recorded_pick("We will pick the best option.")
    assert not spec_structure.recorded_pick("pick any approach you like")
