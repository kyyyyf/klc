"""KLC-139 step-2 — the three `skeleton.*` settings: yml, schema, typed
accessors (AC-10).

`config/settings.yml` ships `skeleton.max_fields`, `skeleton.max_line` and
`skeleton.max_bytes` commented out with their defaults, `_SETTINGS_SCHEMA`
types them `posint`, and three accessors in `settings.py` return the default
for a missing, non-positive or non-integer value.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
for _p in (str(SKILLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import settings  # noqa: E402
import validate_config as _vc  # noqa: E402


def _wsettings(cfg_dir: Path, body: str) -> Path:
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "settings.yml").write_text(body, encoding="utf-8")
    return cfg_dir


def test_doctor_accepts_positive_ints_for_all_three_keys(tmp_path, monkeypatch):
    """AC-10: valid positive-int values pass klc doctor's settings pass and
    come back from the three typed accessors."""
    cfg = _wsettings(
        tmp_path / "config",
        "skeleton:\n  max_fields: 3\n  max_line: 80\n  max_bytes: 1000\n",
    )
    assert _vc.validate_settings(cfg) == []

    proj_root = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(proj_root))
    _wsettings(
        proj_root / ".klc" / "config",
        "skeleton:\n  max_fields: 3\n  max_line: 80\n  max_bytes: 1000\n",
    )
    assert settings.skeleton_max_fields() == 3
    assert settings.skeleton_max_line() == 80
    assert settings.skeleton_max_bytes() == 1000


@pytest.mark.parametrize("key", ["max_fields", "max_line", "max_bytes"])
@pytest.mark.parametrize("bad", [0, -1, "abc"])
def test_doctor_flags_zero_negative_and_string(tmp_path, key, bad):
    """AC-10: klc doctor flags 0, a negative number and a non-numeric string
    for each of the three keys, naming the key, and raises no 'unknown key'
    warning alongside it."""
    value = repr(bad) if isinstance(bad, str) else str(bad)
    cfg = _wsettings(tmp_path / "config", f"skeleton:\n  {key}: {value}\n")
    warns = _vc.validate_settings(cfg)
    assert any(f"skeleton.{key}" in w and "must be a positive integer" in w
               for w in warns), warns
    assert not any("unknown key" in w for w in warns), warns


@pytest.mark.parametrize("case", ["unset", "zero", "abc"])
def test_accessor_returns_default_for_missing_zero_and_non_numeric(
    tmp_path, monkeypatch, case
):
    """AC-10: each accessor falls back to its default for a missing settings
    file, a zero value and a non-numeric string."""
    proj_root = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(proj_root))
    if case != "unset":
        bad = 0 if case == "zero" else "abc"
        value = repr(bad) if isinstance(bad, str) else str(bad)
        _wsettings(
            proj_root / ".klc" / "config",
            f"skeleton:\n  max_fields: {value}\n  max_line: {value}\n"
            f"  max_bytes: {value}\n",
        )
    assert settings.skeleton_max_fields() == 8
    assert settings.skeleton_max_line() == 120
    assert settings.skeleton_max_bytes() == 2_097_152


def test_settings_yml_ships_skeleton_keys_commented():
    """AC-10: the framework config/settings.yml ships the three skeleton keys,
    all commented out, so `core.shared.yaml.parse` sees no `skeleton` key."""
    text = (REPO / "config" / "settings.yml").read_text(encoding="utf-8")
    assert "# skeleton:" in text
    assert "#   max_fields: 8" in text
    assert "#   max_line: 120" in text
    assert "#   max_bytes: 2097152" in text

    sys.path.insert(0, str(REPO))
    from core.shared.yaml import parse as _shared_parse
    data = _shared_parse(text)
    if isinstance(data, dict):
        assert "skeleton" not in data
