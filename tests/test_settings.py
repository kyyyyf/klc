"""Tests for core/skills/settings.py — the consolidated operational-knobs loader.

Covers KLC-100 AC-2 (interleaved precedence ladder) and AC-3 (byte-identical
fallback to legacy when no settings.yml exists), plus the folded review findings:
spec-review F-2 (project-legacy must beat framework-settings), spec-review F-5 /
test-plan-review (cap has a framework-only legacy layer), and impl-review F-2
(a malformed scope degrades, never raises).

The loader's two scope roots are monkeypatched to temp dirs so the framework
scope (normally pinned to the live repo) is injectable.
"""
import sys
from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parent.parent / "core" / "skills"
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

import settings  # noqa: E402


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


def _w(d: Path, name: str, text: str) -> None:
    (d / name).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- AC-2 ladder

def test_full_interleaved_ladder_order(scopes):
    """AC-2: project-settings > project-legacy > framework-settings > framework-legacy > default."""
    proj, fw = scopes
    _w(proj, "settings.yml", "profile: P_SET\n")
    _w(proj, "profile.yml", "profile: P_LEG\n")
    _w(fw, "settings.yml", "profile: F_SET\n")
    _w(fw, "profile.yml", "profile: F_LEG\n")
    assert settings.profile() == "P_SET"
    (proj / "settings.yml").unlink()
    assert settings.profile() == "P_LEG"
    (proj / "profile.yml").unlink()
    assert settings.profile() == "F_SET"
    (fw / "settings.yml").unlink()
    assert settings.profile() == "F_LEG"
    (fw / "profile.yml").unlink()
    assert settings.profile() is None


def test_project_legacy_beats_framework_settings(scopes):
    """AC-2 / spec-review F-2 regression: a framework settings default must NOT
    override a project's explicit legacy choice."""
    proj, fw = scopes
    _w(proj, "profile.yml", "profile: P_LEG\n")
    _w(fw, "settings.yml", "profile: F_SET\n")  # no project settings.yml
    assert settings.profile() == "P_LEG"


def test_project_settings_beats_project_legacy(scopes):
    """AC-2: within the project scope, settings.yml outranks the legacy file."""
    proj, fw = scopes
    _w(proj, "settings.yml", "profile: P_SET\n")
    _w(proj, "profile.yml", "profile: P_LEG\n")
    assert settings.profile() == "P_SET"


# ------------------------------------------------------------- AC-3 fallback

def test_no_settings_file_returns_legacy_profile(scopes):
    """AC-3: no settings.yml at either scope → legacy profile.yml value verbatim."""
    proj, fw = scopes
    _w(fw, "profile.yml", "profile: ue\n")
    assert settings.profile() == "ue"


def test_no_settings_file_returns_legacy_all_knobs(scopes):
    """AC-3: byte-identical fallback for clarify / jira enabled+mode / cap."""
    proj, fw = scopes
    _w(fw, "clarify.yml", "clarify:\n  style: serial\n")
    _w(fw, "jira.yml", "enabled: true\nmode: managed\n")
    _w(fw, "budgets.yml", "consecutive_auto_transitions: 7\n")
    assert settings.clarify_style() == "serial"
    assert settings.jira_enabled() is True
    assert settings.jira_mode() == "managed"
    assert settings.autorun_cap() == 7


def test_commented_key_falls_through(scopes):
    """A commented (absent) knob in a present settings.yml falls through to legacy."""
    proj, fw = scopes
    _w(proj, "settings.yml", "# profile: X\n")
    _w(fw, "profile.yml", "profile: ue\n")
    assert settings.profile() == "ue"


def test_per_knob_independence_mixed_file(scopes):
    """test-plan-review F-2: one knob set, the rest absent → set knob applies,
    every unset knob resolves to legacy (a present-but-absent key must not shadow
    legacy as None)."""
    proj, fw = scopes
    _w(proj, "settings.yml", "profile: P_SET\n")
    _w(fw, "profile.yml", "profile: F_LEG\n")
    _w(fw, "clarify.yml", "clarify:\n  style: serial\n")
    _w(fw, "jira.yml", "enabled: true\nmode: managed\n")
    assert settings.profile() == "P_SET"
    assert settings.clarify_style() == "serial"
    assert settings.jira_enabled() is True
    assert settings.jira_mode() == "managed"


# ---------------------------------------------------------- cap framework-only

def test_cap_skips_project_legacy_layer(scopes):
    """spec-review F-5: the cap's legacy layer is framework-only; a project
    budgets.yml must be ignored for the cap."""
    proj, fw = scopes
    _w(proj, "budgets.yml", "consecutive_auto_transitions: 99\n")
    _w(fw, "budgets.yml", "consecutive_auto_transitions: 20\n")
    assert settings.autorun_cap() == 20


# ------------------------------------------------------------- degrade (F-2)

def test_malformed_settings_degrades_per_knob(scopes, monkeypatch):
    """impl-review F-2: a malformed scope (parser raises) degrades to legacy with
    NO exception propagated out of the accessor."""
    proj, fw = scopes
    _w(proj, "settings.yml", "MALFORMED\n")
    _w(fw, "profile.yml", "profile: ue\n")
    real = settings._parse

    def fake(text):
        if "MALFORMED" in text:
            raise ValueError("boom")
        return real(text)

    monkeypatch.setattr(settings, "_parse", fake)
    assert settings.profile() == "ue"


def test_cap_project_dir_override_ignored(scopes):
    """The cap never takes a project_dir; a jira-style config_dir seam does not
    leak into cap resolution (defense for the framework-only layer)."""
    proj, fw = scopes
    _w(fw, "budgets.yml", "consecutive_auto_transitions: 20\n")
    assert settings.autorun_cap() == 20
