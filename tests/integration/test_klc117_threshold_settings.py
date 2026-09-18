#!/usr/bin/env python3
"""KLC-117 step-5 — AC-10: `advisory.threshold` is an operator-settable knob
defaulting to `medium`, resolved through the existing settings ladder.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import settings  # noqa: E402


@pytest.fixture
def scopes(tmp_path, monkeypatch):
    proj = tmp_path / "proj_config"
    fw = tmp_path / "fw_config"
    proj.mkdir()
    fw.mkdir()
    monkeypatch.setattr(settings, "_proj_config", lambda: proj)
    monkeypatch.setattr(settings, "_fw_config", lambda: fw)
    return proj, fw


def test_default_threshold_is_medium_and_project_override_wins(scopes):
    proj, fw = scopes
    assert settings.advisory_threshold() == "medium"
    (proj / "settings.yml").write_text("advisory:\n  threshold: high\n", encoding="utf-8")
    assert settings.advisory_threshold() == "high"


def test_invalid_threshold_value_falls_back_to_default(scopes):
    proj, fw = scopes
    (proj / "settings.yml").write_text("advisory:\n  threshold: catastrophic\n", encoding="utf-8")
    assert settings.advisory_threshold() == "medium"
