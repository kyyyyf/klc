#!/usr/bin/env python3
"""KLC-131 step-4 — review-fix round 1.

1. plugin_sources_staged() (the --check-if-staged pre-commit trigger) also
   scopes config/phases.yml and config/models.yml: after step-2/step-3 both
   are generator inputs for model: resolution (phase ownership / phase_roles
   respectively), not just core/agents/*.md and plugin_gen.py itself
   (external review MEDIUM).
2. Owner-prompt matching normalises the POSIX path before comparing, so a
   './'-prefixed (but otherwise valid, existing-file) work.prompt is still
   recognised as ownership instead of silently falling back to the stem
   (external review LOW, AC-1).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import phases as _ph      # same module object plugin_gen imports (D-003)
import plugin_gen as _pg


def _point_at(fw: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect both modules' framework_root() to *fw* and clear the phases
    cache so load_phases(force=True) re-reads the fixture tree."""
    monkeypatch.setattr(_pg, "framework_root", lambda: fw)
    monkeypatch.setattr(_ph, "framework_root", lambda: fw)
    monkeypatch.setattr(_ph, "_CACHE", None)


def test_plugin_sources_staged_true_for_phases_and_models_yml() -> None:
    """external review MEDIUM: staging only config/phases.yml, or only
    config/models.yml, puts the pre-commit drift gate in scope — both are
    now generator inputs (phase ownership / phase_roles) for model:
    resolution, not just core/agents/* and plugin_gen.py."""
    assert _pg.plugin_sources_staged(["config/phases.yml"]) is True
    assert _pg.plugin_sources_staged(["config/models.yml"]) is True
    # Existing scope is unaffected.
    assert _pg.plugin_sources_staged(["core/agents/discovery.md"]) is True
    assert _pg.plugin_sources_staged(["core/skills/plugin_gen.py"]) is True
    assert _pg.plugin_sources_staged(["README.md"]) is False
    assert _pg.plugin_sources_staged([]) is False


def test_dotslash_prefixed_prompt_still_recognised_as_owner(tmp_path, monkeypatch):
    """external review LOW (AC-1): a work.prompt of './core/agents/impl.md'
    names the same file as 'core/agents/impl.md' (validate_config already
    accepts it — the file exists) and must still be recognised as
    ownership, not silently fall back to the stem. Fixture: phase `build`
    maps to a rank-3 opus role; models.yml has no `impl` key, so the stem
    alone would fall through to defaults (sonnet)."""
    fw = tmp_path / "fw"
    (fw / "core" / "agents").mkdir(parents=True)
    (fw / "core" / "agents" / "impl.md").write_text(
        "---\nfrontmatter placeholder\n---\nbody\n", encoding="utf-8"
    )
    (fw / "config").mkdir(parents=True)
    (fw / "config" / "phases.yml").write_text(
        "phases:\n"
        "  - id: build\n"
        "    tracks: [M]\n"
        "    work:\n"
        "      prompt: \"./core/agents/impl.md\"\n",
        encoding="utf-8",
    )
    _point_at(fw, monkeypatch)
    models_yml = tmp_path / "models.yml"
    models_yml.write_text(
        "defaults:\n"
        "  provider: anthropic\n"
        "  model: claude-sonnet-5\n"
        "  api_key_env: ANTHROPIC_API_KEY\n"
        "\n"
        "roles:\n"
        "  heavy-reasoning:\n"
        "    provider: anthropic\n"
        "    model: claude-opus-5-5\n"
        "    api_key_env: ANTHROPIC_API_KEY\n"
        "    rank: 3\n"
        "\n"
        "phase_roles:\n"
        "  build: heavy-reasoning\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    _pg.generate_agents(output_dir=out, models_yml=models_yml)
    content = (out / "impl.md").read_text(encoding="utf-8")
    assert "model: opus" in content
