#!/usr/bin/env python3
"""KLC-131 step-1 (AC-8) — generate_agents() reads phases.yml through
phases.load_phases() and fails loudly instead of silently falling back to
stem-only resolution when the phases source is missing or malformed.
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


def _agent_tree(tmp_path: Path) -> Path:
    """A minimal fixture framework tree: one core/agents/*.md source and an
    empty config/ directory. Caller adds (or omits) config/phases.yml."""
    fw = tmp_path / "fw"
    (fw / "core" / "agents").mkdir(parents=True)
    (fw / "core" / "agents" / "retrospective.md").write_text(
        "---\nfrontmatter placeholder\n---\nbody\n", encoding="utf-8"
    )
    (fw / "config").mkdir(parents=True)
    return fw


def test_missing_phases_source_raises_not_silent_stem_fallback(tmp_path, monkeypatch):
    """AC-8: a missing config/phases.yml propagates FileNotFoundError out of
    generate_agents() — it must not silently fall back to stem-only
    resolution for every agent — and no agent file is written."""
    fw = _agent_tree(tmp_path)  # config/ exists, holds no phases.yml
    _point_at(fw, monkeypatch)
    out = tmp_path / "out"
    with pytest.raises(FileNotFoundError):
        _pg.generate_agents(output_dir=out)
    assert not list(out.glob("*.md"))


@pytest.mark.parametrize(
    "phases_yml_body",
    [
        "phases: []\n",
        (
            "phases:\n"
            "  - id: learn\n"
            "    tracks: [M]\n"
            "    work:\n"
            "      prompt: \"core/agents/retrospective.md\"\n"
            "  - id: learn\n"
            "    tracks: [M]\n"
            "    work:\n"
            "      prompt: \"core/agents/retrospective.md\"\n"
        ),
    ],
    ids=["empty-phases-list", "duplicate-phase-ids"],
)
def test_malformed_phases_source_raises(tmp_path, monkeypatch, phases_yml_body):
    """AC-8: a YAML-valid but structurally invalid phases.yml (an empty
    `phases:` list, or two phases sharing one id `learn`) propagates
    ValueError out of generate_agents(); no agent file is written. Both
    cases are the class a bare `_load_raw` call would not catch on its own
    (spec-review F-2) — only `load_phases()`'s own sanity checks (non-empty
    list / unique ids) reject them."""
    fw = _agent_tree(tmp_path)
    (fw / "config" / "phases.yml").write_text(phases_yml_body, encoding="utf-8")
    _point_at(fw, monkeypatch)
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        _pg.generate_agents(output_dir=out)
    assert not list(out.glob("*.md"))
