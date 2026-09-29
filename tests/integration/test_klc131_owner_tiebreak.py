#!/usr/bin/env python3
"""KLC-131 step-3 — a prompt owned by several phases takes the model of the
owner whose role has the highest rank; a rank tie goes to the first owner
in phases.yml order, independent of dict, glob or roles: order (AC-3, AC-9).
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


_PHASES_YAML = (
    "phases:\n"
    "  - id: a-first\n"
    "    tracks: [M]\n"
    "    work:\n"
    "      prompt: \"core/agents/shared-a.md\"\n"
    "  - id: a-second\n"
    "    tracks: [M]\n"
    "    work:\n"
    "      prompt: \"core/agents/shared-a.md\"\n"
    "  - id: b-first\n"
    "    tracks: [M]\n"
    "    work:\n"
    "      prompt: \"core/agents/shared-b.md\"\n"
    "  - id: b-second\n"
    "    tracks: [M]\n"
    "    work:\n"
    "      prompt: \"core/agents/shared-b.md\"\n"
)

# roles: order is low, high, alpha-tier, beta-tier — the phase_roles below
# reference b-first/b-second in the OPPOSITE order to alpha-tier/beta-tier's
# roles: order, so a wrong tie-break that follows roles: order would fail.
_MODELS_YAML = (
    "defaults:\n"
    "  provider: anthropic\n"
    "  model: claude-sonnet-5\n"
    "  api_key_env: ANTHROPIC_API_KEY\n"
    "\n"
    "roles:\n"
    "  low:\n"
    "    provider: anthropic\n"
    "    model: claude-haiku-4-5-20251001\n"
    "    api_key_env: ANTHROPIC_API_KEY\n"
    "    rank: 1\n"
    "  high:\n"
    "    provider: anthropic\n"
    "    model: claude-opus-5-5\n"
    "    api_key_env: ANTHROPIC_API_KEY\n"
    "    rank: 3\n"
    "  alpha-tier:\n"
    "    provider: anthropic\n"
    "    model: claude-opus-5-5\n"
    "    api_key_env: ANTHROPIC_API_KEY\n"
    "    rank: 2\n"
    "  beta-tier:\n"
    "    provider: anthropic\n"
    "    model: claude-haiku-4-5-20251001\n"
    "    api_key_env: ANTHROPIC_API_KEY\n"
    "    rank: 2\n"
    "\n"
    "phase_roles:\n"
    "  a-first: low\n"
    "  a-second: high\n"
    "  b-first: beta-tier\n"
    "  b-second: alpha-tier\n"
)


def test_rank_and_order_tiebreak_fixture(tmp_path, monkeypatch):
    """AC-3, AC-9: shared-a.md is owned by a-first (low, rank 1) and
    a-second (high, rank 3) — the higher-rank role wins even though it's
    listed second, so shared-a is opus. shared-b.md is owned by b-first
    (beta-tier, haiku, rank 2) and b-second (alpha-tier, opus, rank 2) — a
    rank tie, so the FIRST owner in phases.yml order wins, giving haiku,
    even though b-first's role (beta-tier) is listed after alpha-tier under
    roles: and its model id ('claude-haiku...') sorts before alpha-tier's
    ('claude-opus...') so a whole-tuple max(candidates) (no key=) would also
    wrongly pick the larger model id (opus) on this tie (impl-plan-review
    F-1, D-008). Before GREEN this fails on shared-a (step-2's first-owner
    rule gives haiku, not opus)."""
    fw = tmp_path / "fw"
    (fw / "core" / "agents").mkdir(parents=True)
    for name in ("shared-a.md", "shared-b.md"):
        (fw / "core" / "agents" / name).write_text(
            "---\nfrontmatter placeholder\n---\nbody\n", encoding="utf-8"
        )
    (fw / "config").mkdir(parents=True)
    (fw / "config" / "phases.yml").write_text(_PHASES_YAML, encoding="utf-8")
    _point_at(fw, monkeypatch)

    models_yml = tmp_path / "models.yml"
    models_yml.write_text(_MODELS_YAML, encoding="utf-8")

    out = tmp_path / "out"
    _pg.generate_agents(output_dir=out, models_yml=models_yml)

    shared_a = (out / "shared-a.md").read_text(encoding="utf-8")
    shared_b = (out / "shared-b.md").read_text(encoding="utf-8")
    assert "model: opus" in shared_a, shared_a
    assert "model: haiku" in shared_b, shared_b
