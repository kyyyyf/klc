"""KLC-111 step-1 — `scope.infra_paths` gets a `list`-of-strings schema kind
in `validate_config` (AC-2).

Today the key is absent from `_SETTINGS_SCHEMA`, so a bad value is reported as
an "unknown key" warning rather than a type error — the wrong diagnosis. These
tests pin the CORRECT diagnosis once the key and the new `list` kind exist.
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

import validate_config as _vc  # noqa: E402


def _wsettings(tmp_path, body):
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "settings.yml").write_text(body, encoding="utf-8")
    return cfg


def test_scope_infra_paths_declared_as_list_of_strings_kind(tmp_path):
    """AC-2: `_SETTINGS_SCHEMA["scope.infra_paths"]` is a `("list", str)` spec,
    so a well-formed value under the key produces NO warning at all."""
    assert _vc._SETTINGS_SCHEMA.get("scope.infra_paths") == ("list", str)
    cfg = _wsettings(tmp_path, 'scope:\n  infra_paths: [".klc/", "hooks/"]\n')
    warns = _vc.validate_settings(cfg)
    assert warns == [], warns


def test_klc_doctor_warns_when_infra_paths_value_is_not_a_list(tmp_path):
    """AC-2: a scalar value under `scope.infra_paths` warns with a type
    message naming the key — not the stale 'unknown key' diagnosis."""
    cfg = _wsettings(tmp_path, "scope:\n  infra_paths: not-a-list\n")
    warns = _vc.validate_settings(cfg)
    assert any("scope.infra_paths" in w and "must be a list" in w for w in warns), warns
    assert not any("unknown key" in w for w in warns), warns


def test_klc_doctor_warns_when_infra_paths_has_non_string_element(tmp_path):
    """AC-2: a non-string element (`[".klc/", 7]`) warns, naming the offending
    index and its value."""
    cfg = _wsettings(tmp_path, 'scope:\n  infra_paths: [".klc/", 7]\n')
    warns = _vc.validate_settings(cfg)
    assert any("scope.infra_paths[1]" in w and "must be a string" in w for w in warns), warns


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
