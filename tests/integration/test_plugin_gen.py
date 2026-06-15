#!/usr/bin/env python3
"""Tests for the klc plugin-gen generator (AC-2).

The generator copies core/agents/*.md into klc-plugin/agents/ with model:
frontmatter resolved from models.yml. These tests run the generator in
isolated temp dirs.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import plugin_gen as _pg
import models as _m


def _agent_sources() -> list[Path]:
    """Top-level .md files in core/agents/ (not subdirectories)."""
    return [p for p in (FW_ROOT / "core" / "agents").glob("*.md")]


def test_subagents_generated() -> None:
    """Generator produces one agent file per core/agents/*.md source."""
    sources = _agent_sources()
    assert sources, "core/agents/ has no .md files — check FW_ROOT"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "agents"
        _pg.generate_agents(output_dir=out)
        for src in sources:
            dest = out / src.name
            assert dest.exists(), (
                f"generator did not produce agents/{src.name}"
            )


def test_model_frontmatter_from_models_yml() -> None:
    """Each generated agent has a model: field resolved from models.yml."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "agents"
        _pg.generate_agents(output_dir=out)
        for dest in out.glob("*.md"):
            content = dest.read_text(encoding="utf-8")
            assert content.startswith("---\n"), (
                f"agents/{dest.name} missing frontmatter"
            )
            # Extract frontmatter block
            end = content.index("\n---\n", 4)
            fm_text = content[4:end]
            assert "model:" in fm_text, (
                f"agents/{dest.name} frontmatter missing 'model:' — "
                f"frontmatter: {fm_text!r}"
            )


def test_regen_reflects_models_change() -> None:
    """After changing a model in models.yml, regenerating updates the frontmatter."""
    import re

    models_path = FW_ROOT / "config" / "models.yml"
    original = models_path.read_text(encoding="utf-8")

    # Patch the coding role model by string replacement (avoids yaml re-dump issues)
    modified_yml = re.sub(
        r"(coding:.*?model:\s*)claude-sonnet-4-6",
        r"\1claude-test-regen-marker",
        original,
        count=1,
        flags=re.DOTALL,
    )
    assert "claude-test-regen-marker" in modified_yml, (
        "regex substitution failed — check models.yml format"
    )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "agents"
        # Generate with modified models.yml written to a temp file
        tmp_models = Path(tmp) / "models.yml"
        tmp_models.write_text(modified_yml, encoding="utf-8")

        _pg.generate_agents(output_dir=out, models_yml=tmp_models)

        # Find an agent that maps to the coding role (e.g. discovery-lite)
        dl_agent = out / "discovery-lite.md"
        assert dl_agent.exists(), "discovery-lite.md not generated"
        content = dl_agent.read_text(encoding="utf-8")
        # The modified model name should appear in the frontmatter
        assert "claude-test-regen-marker" in content or "test-regen" in content, (
            f"regen did not pick up models.yml change in discovery-lite.md; "
            f"content start: {content[:300]!r}"
        )
