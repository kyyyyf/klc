"""KLC-100 config-hygiene acceptance tests.

Each resolver honoring config/settings.yml, plus doctor / install / README /
deprecation-marker acceptance. Grown per build step. The four resolvers funnel
through core/skills/settings.py (see tests/test_settings.py for the loader ladder).
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
for _p in (str(SKILLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load(mod_name: str, relpath: str):
    """Import a (possibly hyphenated) script by path as a fresh module.

    Registered in sys.modules before exec so dataclasses (which resolve
    cls.__module__ via sys.modules) load correctly."""
    spec = importlib.util.spec_from_file_location(mod_name, REPO / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _proj_cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / ".klc" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    return cfg


# ============================================================ step-2: profile

def test_profile_resolve_honors_settings(tmp_path, monkeypatch):
    """AC-4: profile-resolve returns the profile set in settings.yml."""
    (_proj_cfg(tmp_path) / "settings.yml").write_text("profile: generic\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    pr = _load("profile_resolve", "core/skills/profile-resolve.py")
    name, _src = pr._profile_selector()
    assert name == "generic"


def test_doctor_profile_manifest_honors_settings(tmp_path, monkeypatch):
    """AC-4 / F-1: doctor resolves the profile via the settings loader, not a raw
    read of config/profile.yml (a settings.yml profile is honored)."""
    (_proj_cfg(tmp_path) / "settings.yml").write_text("profile: zzz_settings\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    doc = _load("klc_doctor", "core/phases/doctor.py")
    errs = doc._profile_manifest()
    assert any("zzz_settings" in e for e in errs)


def test_doctor_profile_honors_project_override(tmp_path, monkeypatch):
    """AC-4 / F-1: doctor now honors the PROJECT .klc/config/profile.yml override
    it previously ignored (it read only the framework config/profile.yml)."""
    (_proj_cfg(tmp_path) / "profile.yml").write_text("profile: zzz_legacy\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    doc = _load("klc_doctor", "core/phases/doctor.py")
    errs = doc._profile_manifest()
    assert any("zzz_legacy" in e for e in errs)


# ==================================================== step-3: clarify + jira

import clarify_config  # noqa: E402
import jira_config as jc  # noqa: E402


def _valid_jira_yml(enabled: str, mode: str) -> str:
    return (
        f"enabled: {enabled}\nmode: {mode}\nmanaged_tickets: []\n"
        "site:\n  base_url: 'https://jira.example.com'\n"
        "  project_key: KLC\n  auth_env: JIRA_API_TOKEN\n"
        "gitlab:\n  base_url: 'https://gitlab.example.com/g/r'\n"
        "  blob_url: '{base_url}/-/blob/{branch}/{path}'\n"
        "status_mapping:\n"
        "  klc_to_jira:\n    review: 'In Review'\n"
        "  jira_to_klc:\n    'In Review': [review]\n"
    )


def test_clarify_style_honors_settings(tmp_path, monkeypatch):
    """AC-5: clarify style comes from settings.yml when set."""
    (_proj_cfg(tmp_path) / "settings.yml").write_text("clarify:\n  style: serial\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert clarify_config.load_clarify_style() == "serial"


def test_clarify_style_fail_closed_preserved(tmp_path, monkeypatch):
    """AC-5: an invalid style (even from settings.yml) still raises — fail-closed."""
    (_proj_cfg(tmp_path) / "settings.yml").write_text("clarify:\n  style: bogus\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import pytest
    with pytest.raises(clarify_config.ClarifyConfigError):
        clarify_config.load_clarify_style()


def test_jira_enabled_mode_honor_settings(tmp_path):
    """AC-6: settings.yml jira.enabled/mode outrank the same-scope jira.yml legacy."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "jira.yml").write_text(_valid_jira_yml("false", "mirror"), encoding="utf-8")
    (cfg / "settings.yml").write_text("jira:\n  enabled: true\n  mode: managed\n", encoding="utf-8")
    loaded = jc.load(config_dir=cfg)
    assert loaded.enabled is True
    assert loaded.mode == "managed"


def test_jira_load_config_dir_managed_preserved(tmp_path):
    """impl-review F-1: jc.load(config_dir=X) with enabled:true/mode:managed in
    X/jira.yml (no settings.yml) STILL yields a managed config after wiring —
    the config_dir injection seam is honored."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "jira.yml").write_text(_valid_jira_yml("true", "managed"), encoding="utf-8")
    loaded = jc.load(config_dir=cfg)
    assert loaded.enabled is True
    assert loaded.mode == "managed"


def test_jira_validation_unchanged(tmp_path):
    """AC-6: status_mapping still required; a bad mode still raises."""
    import pytest
    cfg = tmp_path / "config"
    cfg.mkdir()
    # bad mode -> raise (settings.yml sets the invalid mode; validation must still fire)
    (cfg / "jira.yml").write_text(_valid_jira_yml("true", "mirror"), encoding="utf-8")
    (cfg / "settings.yml").write_text("jira:\n  mode: bogus\n", encoding="utf-8")
    with pytest.raises(jc.JiraConfigError):
        jc.load(config_dir=cfg)
    # missing status_mapping -> raise
    (cfg / "settings.yml").unlink()
    (cfg / "jira.yml").write_text(
        "enabled: true\nmode: mirror\nsite:\n  base_url: 'https://j.example.com'\n"
        "  auth_env: T\ngitlab:\n  blob_url: '{base_url}/-/blob/{branch}/{path}'\n",
        encoding="utf-8",
    )
    with pytest.raises(jc.JiraConfigError):
        jc.load(config_dir=cfg)


# ==================================================== step-4: autorun cap

def test_autorun_cap_honors_settings(tmp_path, monkeypatch):
    """AC-7: the cap comes from settings.yml (project scope) when set."""
    (_proj_cfg(tmp_path) / "settings.yml").write_text(
        "autorun:\n  consecutive_auto_transitions: 5\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_AUTORUN_CAP", raising=False)
    ar = _load("klc_autorunner", "core/skills/autorunner.py")
    assert ar._cap() == 5


def test_autorun_cap_env_beats_settings(tmp_path, monkeypatch):
    """AC-7: KLC_AUTORUN_CAP env stays ABOVE settings.yml in the ladder."""
    (_proj_cfg(tmp_path) / "settings.yml").write_text(
        "autorun:\n  consecutive_auto_transitions: 5\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_AUTORUN_CAP", "7")
    ar = _load("klc_autorunner", "core/skills/autorunner.py")
    assert ar._cap() == 7


def test_autorun_cap_no_project_budgets_read(tmp_path, monkeypatch):
    """AC-7 / F-5: the cap does NOT consult a project .klc/config/budgets.yml —
    its legacy layer is framework-only (the framework cap is 20)."""
    (_proj_cfg(tmp_path) / "budgets.yml").write_text(
        "consecutive_auto_transitions: 99\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_AUTORUN_CAP", raising=False)
    ar = _load("klc_autorunner", "core/skills/autorunner.py")
    assert ar._cap() == 20


# ======== step-5: settings.yml + install seed + README + deprecation markers

import subprocess  # noqa: E402
from core.shared.yaml import parse as _yparse  # noqa: E402

CONFIG_DIR = REPO / "config"


def test_settings_yml_exists_and_documents_four_knobs():
    """AC-1 (keyword/structural, review D-2): each of the four knob keys appears."""
    text = (CONFIG_DIR / "settings.yml").read_text(encoding="utf-8")
    for knob in ("profile", "jira", "clarify", "autorun"):
        assert knob in text, knob


def test_settings_yml_ships_all_knobs_commented():
    """AC-1 / F-3: the framework file parses to NO active key (all commented)."""
    data = _yparse((CONFIG_DIR / "settings.yml").read_text(encoding="utf-8"))
    assert not data


def test_install_seeds_commented_settings(tmp_path):
    """AC-11: klc install seeds a commented .klc/config/settings.yml."""
    proj = tmp_path / "proj"
    proj.mkdir()
    r = subprocess.run(
        [sys.executable, str(REPO / "core" / "phases" / "install.py"), str(proj)],
        capture_output=True, text=True)
    seeded = proj / ".klc" / "config" / "settings.yml"
    assert seeded.exists(), r.stderr
    assert not _yparse(seeded.read_text(encoding="utf-8"))


def test_readme_groups_system_functional():
    """AC-8 (keyword/structural, review D-2): SYSTEM + FUNCTIONAL headings, every
    config filename present, settings.yml named the front door."""
    text = (CONFIG_DIR / "README.md").read_text(encoding="utf-8")
    assert "SYSTEM" in text and "FUNCTIONAL" in text
    assert "settings.yml" in text
    for fname in ("phases.yml", "models.yml", "tiers.yml", "sentinels.yml",
                  "constitution.yml", "coverage-taxonomy.yml",
                  "elicitation-techniques.csv", "reviewers.yml", "jira.yml",
                  "budgets.yml", "clarify.yml", "ticket-id.yml", "profile.yml",
                  "reviewer-allowlist.seed.yml"):
        assert fname in text, fname


def test_jira_yml_deprecation_markers():
    """AC-10 / F-4: jira.yml marks BOTH url_template and sync.* DEPRECATED (not deleted)."""
    text = (CONFIG_DIR / "jira.yml").read_text(encoding="utf-8")
    assert text.count("DEPRECATED") >= 2
    assert "url_template" in text  # still present (live, not deleted)
    assert "\nsync:" in text       # still present
    assert "status_mapping" in text


def test_reviewers_yml_live_key_comment():
    """AC-10: reviewers.yml notes mutation_score_threshold is live (test-writer.py)."""
    text = (CONFIG_DIR / "reviewers.yml").read_text(encoding="utf-8")
    assert "LIVE" in text and "test-writer" in text and "mutation_score_threshold" in text


# ================================== step-6: doctor + validate_config settings

import validate_config as _vc  # noqa: E402


def _wsettings(tmp_path, body):
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "settings.yml").write_text(body, encoding="utf-8")
    return cfg


def test_doctor_flags_unknown_settings_key(tmp_path):
    """AC-9: an unknown TOP-LEVEL settings.yml key is flagged."""
    cfg = _wsettings(tmp_path, "bogus_top: 1\n")
    warns = _vc.validate_settings(cfg)
    assert any("bogus_top" in w for w in warns)


def test_doctor_flags_nested_unknown_key(tmp_path):
    """AC-9 / impl-review F-3: a NESTED typo is flagged, not silently no-op'd."""
    cfg = _wsettings(tmp_path, "jira:\n  enabld: true\n")
    warns = _vc.validate_settings(cfg)
    assert any("jira.enabld" in w for w in warns)


def test_doctor_flags_bad_enum_values(tmp_path):
    """AC-9: bad enum / type values each flagged."""
    cfg = _wsettings(
        tmp_path,
        "profile: 123\njira:\n  mode: bogus\nclarify:\n  style: nope\n"
        "autorun:\n  consecutive_auto_transitions: -5\n")
    warns = _vc.validate_settings(cfg)
    joined = " ".join(warns)
    assert "jira.mode" in joined
    assert "clarify.style" in joined
    assert "autorun.consecutive_auto_transitions" in joined
    assert "profile" in joined


def test_doctor_ok_when_settings_absent(tmp_path):
    """AC-9: no settings.yml at all → no warning, no error."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    assert _vc.validate_settings(cfg) == []


def test_commented_settings_no_validate_warning():
    """AC-9 / impl-review F-3: the shipped fully-commented framework settings.yml
    (parses to None) produces NO validate warning and doctor stays green."""
    assert _vc.validate_settings(CONFIG_DIR) == []
    doc = _load("klc_doctor2", "core/phases/doctor.py")
    errs = doc._config_validation()
    assert not any("settings.yml" in e for e in errs)
