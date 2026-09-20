"""KLC-111 step-2 — `scope_delta.compare` drops its infra filter from the
settings-backed `module_vocabulary.is_infra`, not from private literals
(AC-3), and the drop-set widening `.github/`/`.gitlab/` mandated by AC-1 is
pinned in both directions (impl-plan-review F-2 / test-plan N-1 / D-202).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = _FW_ROOT / "core" / "skills"
sys.path.insert(0, str(_SKILLS))

import scope_delta as sd  # noqa: E402

SCOPE_DELTA_SRC = _SKILLS / "scope_delta.py"


def _isolate_settings(monkeypatch, tmp_path):
    """Point module_vocabulary's settings ladder at empty temp dirs, so the
    real repo's config/settings.yml and .klc/config/settings.yml can never
    leak into these tests (hermetic — nothing here reads the live index or
    live config)."""
    proj = tmp_path / "proj_config"
    fw = tmp_path / "fw_config"
    proj.mkdir(parents=True, exist_ok=True)
    fw.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sd._mv._settings, "_proj_config", lambda: proj)
    monkeypatch.setattr(sd._mv._settings, "_fw_config", lambda: fw)


def _run_compare(monkeypatch, tmp_path, changed, planned, modules):
    _isolate_settings(monkeypatch, tmp_path)
    idx = tmp_path / "index"
    idx.mkdir(exist_ok=True)
    (idx / "modules.json").write_text(json.dumps(modules), encoding="utf-8")
    monkeypatch.setattr(sd, "klc_index_dir", lambda: idx)
    monkeypatch.setattr(sd, "_git_changed_files", lambda root: list(changed))
    monkeypatch.setattr(sd, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sd._lc, "read_meta",
                        lambda t: {"affected_modules": list(planned)})
    return sd.compare("KLC-XXX")


def test_compare_drops_files_matching_settings_infra_list(monkeypatch, tmp_path):
    """AC-3: `scope_delta.compare`'s infra drop-list comes from the settings
    resolver (via `module_vocabulary.is_infra`), not a private literal — a
    custom settings-declared entry (`vendor/`) is dropped exactly like the
    built-in ones."""
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setattr(sd._mv._settings, "scope_infra_paths", lambda: ["vendor/"])
    d = _run_compare(monkeypatch, tmp_path, changed=["vendor/x.py"], planned=[],
                     modules={"modules": []})
    assert d.get("skipped") == "no changed files detected", d
    assert "vendor/x.py" not in d.get("unknown_files", []), d


def test_source_has_no_hard_coded_infra_prefixes_or_files_literal():
    """AC-3: the literals `_INFRA_PREFIXES` and `_INFRA_FILES` no longer
    appear anywhere in `core/skills/scope_delta.py` — the comment explaining
    WHY each path is infra moved into `module_vocabulary` along with the
    rule itself."""
    text = SCOPE_DELTA_SRC.read_text(encoding="utf-8")
    assert "_INFRA_PREFIXES" not in text
    assert "_INFRA_FILES" not in text


def test_github_and_gitlab_paths_move_from_expansion_to_excused(monkeypatch, tmp_path):
    """AC-3 (N-1): today's literal drop-list (`.klc/`, `hooks/` prefixes;
    `README.md` exact) does NOT excuse `.github/`/`.gitlab/` — probed inline
    below, those paths pass the OLD filter untouched and would land in
    `unknown_files` -> `expansion`. AC-1's mandated default is a strict
    superset that adds `.github/` and `.gitlab/`, so the NEW settings-driven
    rule excuses the same paths — a deliberate widening (impl-plan-review
    F-2 / D-202), pinned here rather than left as a side effect."""
    old_prefixes = (".klc/", "hooks/")
    old_files = ("README.md",)
    changed = [".github/workflows/ci.yml", ".gitlab/ci.yml"]
    old_survivors = [f for f in changed
                     if not f.startswith(old_prefixes) and f not in old_files]
    assert old_survivors == changed, (
        "today's literals must NOT drop .github/.gitlab paths — the premise "
        "of this widening test")

    d = _run_compare(monkeypatch, tmp_path, changed=changed, planned=[],
                     modules={"modules": []})
    assert d.get("skipped") == "no changed files detected", d
    assert d.get("unknown_files", []) == [], d


def test_dot_klc_hooks_and_root_readme_stay_excused_byte_identically(monkeypatch, tmp_path):
    """AC-3 (N-1, the genuine non-regression half): `.klc/x`, `hooks/y` and
    the root `README.md` stay excused exactly as they were before the
    settings-driven rewrite — nothing else new drops out with them."""
    changed = [".klc/tickets/KLC-1/meta.json", "hooks/pre-commit", "README.md"]
    d = _run_compare(monkeypatch, tmp_path, changed=changed, planned=[],
                     modules={"modules": []})
    assert d.get("skipped") == "no changed files detected", d


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
