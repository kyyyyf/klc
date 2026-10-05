"""KLC-115 step-1: verify.* budget accessors on settings.py (AC-12) and their
registration in validate_config._SETTINGS_SCHEMA (design-addendum-r2, F-107).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import settings  # noqa: E402
import validate_config  # noqa: E402


@pytest.fixture
def scopes(tmp_path, monkeypatch):
    """A project config dir and a framework config dir, both injected."""
    proj = tmp_path / "proj_config"
    fw = tmp_path / "fw_config"
    proj.mkdir()
    fw.mkdir()
    monkeypatch.setattr(settings, "_proj_config", lambda: proj)
    monkeypatch.setattr(settings, "_fw_config", lambda: fw)
    return proj, fw


def test_budgets_resolve_through_settings_resolve_with_override(scopes):
    proj, fw = scopes
    assert settings.verify_step_budget() == 120
    assert settings.verify_node_budget() == 120
    assert settings.verify_arm_budget() == 600

    (proj / "settings.yml").write_text(
        "verify:\n  step_budget_seconds: 45\n", encoding="utf-8")
    assert settings.verify_step_budget() == 45
    assert settings.verify_node_budget() == 120   # untouched sibling stays default


def test_missing_or_malformed_settings_file_uses_hard_default(scopes, monkeypatch):
    proj, fw = scopes
    (proj / "settings.yml").write_text("verify:\n  step_budget_seconds: 45\n",
                                       encoding="utf-8")
    real = settings._parse

    def fake(text):
        if "step_budget_seconds" in text:
            raise ValueError("boom")
        return real(text)

    monkeypatch.setattr(settings, "_parse", fake)


def test_verify_keys_are_registered_in_the_settings_schema(scopes):
    proj, fw = scopes
    fw_settings = fw / "settings.yml"
    fw_settings.write_text(
        "verify:\n"
        "  step_budget_seconds: 30\n"
        "  node_budget_seconds: 30\n"
        "  arm_budget_seconds: 90\n",
        encoding="utf-8")
    warnings = validate_config.validate_settings(fw)
    assert not any("unknown key" in w for w in warnings), warnings


def test_removed_knobs_are_gone_and_kept_ones_stay(scopes):
    """KLC-174: only the replay's knobs go; the arm and step budgets stay."""
    assert not hasattr(settings, "verify_entry_budget")
    assert not hasattr(settings, "build_verify_steps")
    assert settings.verify_arm_budget() == 600 and settings.verify_step_budget() == 120
    proj, fw = scopes
    (fw / "settings.yml").write_text("verify:\n  entry_budget_seconds: 30\n", encoding="utf-8")
    assert any("entry_budget_seconds" in w for w in validate_config.validate_settings(fw))
