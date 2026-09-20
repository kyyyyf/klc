"""KLC-111 step-1 — `scope.infra_paths` as a real settings knob (AC-1).

`settings.scope_infra_paths()` is a pure ladder resolver (D-003): it returns
whatever `resolve()` yields, including `None` when nothing declares the key —
the hard default and its degrade live one layer up, in `module_vocabulary`
(step-2). What THIS layer owns is: the key resolves through the normal
project-before-framework ladder, and the framework-shipped `config/settings.yml`
documents the canonical default list as a commented, flow-list block so the
value round-trips byte-identically when a project turns it on.
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

DEFAULT_INFRA = [".klc/", "hooks/", ".github/", ".gitlab/", "README.md"]


@pytest.fixture
def scopes(tmp_path, monkeypatch):
    """A project config dir and a framework config dir, both injected — same
    pattern as tests/test_settings.py."""
    proj = tmp_path / "proj_config"
    fw = tmp_path / "fw_config"
    proj.mkdir()
    fw.mkdir()
    monkeypatch.setattr(settings, "_proj_config", lambda: proj)
    monkeypatch.setattr(settings, "_fw_config", lambda: fw)
    return proj, fw


def _w(d: Path, name: str, text: str) -> None:
    (d / name).write_text(text, encoding="utf-8")


def test_default_infra_list_is_dot_klc_hooks_github_gitlab_readme(scopes):
    """AC-1: with nothing declared anywhere, the resolver stays a pure ladder
    and returns None (D-003) — no hidden default lives in settings.py.
    Declared at the framework layer, the resolver returns the canonical
    default list verbatim, in order: `.klc/`, `hooks/`, `.github/`,
    `.gitlab/`, `README.md`. That is the same list the shipped
    `config/settings.yml` documents as its commented default, proving the
    documented default and the resolved value are one and the same."""
    proj, fw = scopes
    assert settings.scope_infra_paths() is None

    _w(fw, "settings.yml",
       "scope:\n"
       '  infra_paths: [".klc/", "hooks/", ".github/", ".gitlab/", "README.md"]\n')
    assert settings.scope_infra_paths() == DEFAULT_INFRA

    shipped = (REPO / "config" / "settings.yml").read_text(encoding="utf-8")
    assert '[".klc/", "hooks/", ".github/", ".gitlab/", "README.md"]' in shipped, (
        "the shipped config/settings.yml must document the default list "
        "verbatim as a commented flow-list block")


def test_settings_yml_override_replaces_default_infra_list(scopes):
    """AC-1: a project's `settings.yml` override replaces the default list
    wholesale (not merged) via the existing resolve() ladder — project layer
    beats framework layer, same as every other knob."""
    proj, fw = scopes
    _w(fw, "settings.yml",
       "scope:\n"
       '  infra_paths: [".klc/", "hooks/", ".github/", ".gitlab/", "README.md"]\n')
    _w(proj, "settings.yml", 'scope:\n  infra_paths: ["vendor/", "build/"]\n')
    assert settings.scope_infra_paths() == ["vendor/", "build/"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
