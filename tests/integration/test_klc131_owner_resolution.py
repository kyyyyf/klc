#!/usr/bin/env python3
"""KLC-131 step-2 — generate_agents() resolves model: from the phase that
owns a prompt (Phase.prompt == "core/agents/<file>"); a prompt with no
owner keeps today's stem-then-defaults resolution, and the name:/
description: lines stay stem-based (AC-1, AC-2, AC-4, AC-5, AC-6, AC-7).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import models as _m
import phases as _ph      # same module object plugin_gen imports (D-003)
import plugin_gen as _pg


def _point_at(fw: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect both modules' framework_root() to *fw* and clear the phases
    cache so load_phases(force=True) re-reads the fixture tree."""
    monkeypatch.setattr(_pg, "framework_root", lambda: fw)
    monkeypatch.setattr(_ph, "framework_root", lambda: fw)
    monkeypatch.setattr(_ph, "_CACHE", None)


def _make_fw(tmp_path: Path, phases_yaml: str, agent_names: list[str]) -> Path:
    """A fixture framework tree: one core/agents/<name>.md per *agent_names*
    and *phases_yaml* written to config/phases.yml."""
    fw = tmp_path / "fw"
    (fw / "core" / "agents").mkdir(parents=True)
    for name in agent_names:
        (fw / "core" / "agents" / name).write_text(
            "---\nfrontmatter placeholder\n---\nbody\n", encoding="utf-8"
        )
    (fw / "config").mkdir(parents=True)
    (fw / "config" / "phases.yml").write_text(phases_yaml, encoding="utf-8")
    return fw


def _write_models(tmp_path: Path, name: str, body: str) -> Path:
    dest = tmp_path / name
    dest.write_text(body, encoding="utf-8")
    return dest


def test_single_owner_prompt_resolves_owner_role_not_stem(tmp_path, monkeypatch):
    """AC-1: fixture phase `build` owns core/agents/impl.md and maps to a
    rank-3 opus role; `models.yml` has no `impl` key, so the stem alone
    would fall through to defaults (sonnet). generate_agents() must use the
    owner's role instead."""
    fw = _make_fw(
        tmp_path,
        "phases:\n"
        "  - id: build\n"
        "    tracks: [M]\n"
        "    work:\n"
        "      prompt: \"core/agents/impl.md\"\n",
        ["impl.md"],
    )
    _point_at(fw, monkeypatch)
    models_yml = _write_models(
        tmp_path,
        "models.yml",
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
    )
    out = tmp_path / "out"
    _pg.generate_agents(output_dir=out, models_yml=models_yml)
    content = (out / "impl.md").read_text(encoding="utf-8")
    assert "model: opus" in content


def test_generate_agents_reads_fixture_phases_via_framework_root_monkeypatch(
    tmp_path, monkeypatch
):
    """AC-6: fixture phase `learn` owns core/agents/retrospective.md and
    maps to a haiku role while `defaults` is sonnet; the fixture tree is
    injected purely by monkeypatching framework_root() on both `phases` and
    `plugin_gen` (phases.py is not edited, load_phases() stays the sole
    reader)."""
    fw = _make_fw(
        tmp_path,
        "phases:\n"
        "  - id: learn\n"
        "    tracks: [M]\n"
        "    work:\n"
        "      prompt: \"core/agents/retrospective.md\"\n",
        ["retrospective.md"],
    )
    _point_at(fw, monkeypatch)
    models_yml = _write_models(
        tmp_path,
        "models.yml",
        "defaults:\n"
        "  provider: anthropic\n"
        "  model: claude-sonnet-5\n"
        "  api_key_env: ANTHROPIC_API_KEY\n"
        "\n"
        "roles:\n"
        "  local-simple:\n"
        "    provider: anthropic\n"
        "    model: claude-haiku-4-5-20251001\n"
        "    api_key_env: ANTHROPIC_API_KEY\n"
        "    rank: 1\n"
        "\n"
        "phase_roles:\n"
        "  learn: local-simple\n",
    )
    out = tmp_path / "out"
    _pg.generate_agents(output_dir=out, models_yml=models_yml)
    content = (out / "retrospective.md").read_text(encoding="utf-8")
    assert "model: haiku" in content


def test_unowned_prompt_keeps_stem_or_default_resolution(tmp_path, monkeypatch):
    """AC-2 (regression pin): a prompt no phase owns keeps stem-then-defaults
    resolution. `intake`'s work.prompt is empty, so it owns nothing and the
    stem `intake` applies; `intake-triage` and `inventory` are not phase ids
    at all, so they always resolved by stem, owner or no owner."""
    fw = _make_fw(
        tmp_path,
        "phases:\n"
        "  - id: intake\n"
        "    tracks: [M]\n"
        "    work:\n"
        "      prompt: \"\"\n"
        "  - id: learn\n"
        "    tracks: [M]\n"
        "    work:\n"
        "      prompt: \"core/agents/retrospective.md\"\n",
        ["intake.md", "intake-triage.md", "inventory.md", "retrospective.md"],
    )
    _point_at(fw, monkeypatch)
    models_yml = _write_models(
        tmp_path,
        "models.yml",
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
        "  local-simple:\n"
        "    provider: anthropic\n"
        "    model: claude-haiku-4-5-20251001\n"
        "    api_key_env: ANTHROPIC_API_KEY\n"
        "    rank: 1\n"
        "\n"
        "phase_roles:\n"
        "  intake-triage: local-simple\n"
        "  intake: heavy-reasoning\n",
    )
    out = tmp_path / "out"
    _pg.generate_agents(output_dir=out, models_yml=models_yml)

    assert "model: haiku" in (out / "intake-triage.md").read_text(encoding="utf-8")
    assert "model: opus" in (out / "intake.md").read_text(encoding="utf-8")
    assert "model: sonnet" in (out / "inventory.md").read_text(encoding="utf-8")
    # learn owns retrospective.md but has no phase_roles entry -> defaults.
    assert "model: sonnet" in (out / "retrospective.md").read_text(encoding="utf-8")


def test_frontmatter_five_line_shape_unchanged(tmp_path):
    """AC-4 (regression pin): the real tree's generated frontmatter keeps its
    five-line shape and is byte-identical to the committed plugin agent on
    every line except line 4 (model:)."""
    out = tmp_path / "out"
    _pg.generate_agents(output_dir=out)
    committed = FW_ROOT / "klc-plugin" / "agents"

    for dest in sorted(out.glob("*.md")):
        lines = dest.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "---"
        assert lines[1] == f"name: klc-{dest.stem}"
        assert lines[2] == f"description: klc {dest.stem} phase agent"
        assert lines[3].startswith("model: ")
        assert lines[4] == "---"

        committed_file = committed / dest.name
        committed_lines = committed_file.read_text(encoding="utf-8").splitlines()
        assert len(committed_lines) == len(lines), dest.name
        for i, (a, b) in enumerate(zip(lines, committed_lines)):
            if i == 3:
                continue
            assert a == b, (dest.name, i, a, b)


def test_real_tree_owner_model_matches_phase_resolver_cc_model(tmp_path):
    """AC-7, AC-2 (regression pin): every owned prompt's generated model:
    line equals an independently computed max-by-rank alias over its real
    phases.yml owners (in file order), and intake-triage/inventory/docgen/
    decompose stay unowned, carrying cc_alias(Models.resolve(stem).model)."""
    mc = _m.load_models(force=True)
    ph = _ph.load_phases(force=True)

    out = tmp_path / "out"
    _pg.generate_agents(output_dir=out)

    owners_by_file: dict[str, list[str]] = {}
    for p in ph.ordered:
        if not p.prompt:
            continue
        name = p.prompt.rsplit("/", 1)[-1]
        owners_by_file.setdefault(name, []).append(p.id)

    for dest in sorted(out.glob("*.md")):
        keys = owners_by_file.get(dest.name) or [dest.stem]
        candidates: list[tuple[int, str]] = []
        for key in keys:
            try:
                resolved = mc.resolve(key)
            except (KeyError, ValueError):
                candidates.append((mc.defaults.rank, mc.defaults.model))
                continue
            role = mc.roles.get(resolved.role)
            rank = role.rank if role is not None else mc.defaults.rank
            candidates.append((rank, resolved.model))
        expected_model = max(candidates, key=lambda c: c[0])[1]
        expected_line = f"model: {_pg.cc_alias(expected_model)}"

        lines = dest.read_text(encoding="utf-8").splitlines()
        assert lines[3] == expected_line, (dest.name, lines[3], expected_line)

    for unowned_stem in ("intake-triage", "inventory", "docgen", "decompose"):
        assert f"{unowned_stem}.md" not in owners_by_file, unowned_stem
