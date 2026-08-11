#!/usr/bin/env python3
"""KLC-102 — plugin_gen generates the passthrough skills + manifest byte-exact.

These tests pin the generator to the CURRENTLY committed delivery layer
(`klc-plugin/skills/<verb>/SKILL.md` and `.claude-plugin/plugin.json`). The
generator reproduces existing content byte-for-byte (constraint C-003); it does
not "improve" it. The whole-plugin drift-guard lives in
`tests/test_plugin_agents_in_sync.py`; this file exercises the generators and
their `main()` wiring directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW))

import plugin_gen as pg  # noqa: E402

SKILLS_DIR = FW / "klc-plugin" / "skills"
MANIFEST_PATH = FW / "klc-plugin" / ".claude-plugin" / "plugin.json"
COMMANDS_DIR = FW / "klc-plugin" / "commands"
PLUGIN_DIR = FW / "klc-plugin"


# --------------------------------------------------------------------------
# step-1 — VERB_SPECS + generate_skills (byte-exact passthrough skills)
# --------------------------------------------------------------------------

def test_skill_verbs_are_the_eight_passthrough() -> None:
    """AC-1: SKILL_VERBS is exactly the eight passthrough verbs — no more, no
    less (publish is command-only, run/discuss-feature are bespoke)."""
    assert pg.SKILL_VERBS == {
        "intake", "status", "next", "ack", "ship", "jump", "abort", "step",
    }


def test_generate_skills_byte_exact(tmp_path) -> None:
    """AC-1 / C-003: each generated ``<verb>/SKILL.md`` reproduces the committed
    file byte-for-byte."""
    pg.generate_skills(output_dir=tmp_path)
    for v in pg.SKILL_VERBS:
        gen = (tmp_path / v / "SKILL.md").read_bytes()
        committed = (SKILLS_DIR / v / "SKILL.md").read_bytes()
        assert gen == committed, f"generated skill for {v!r} drifts from committed"


def test_generate_skills_skips_publish(tmp_path) -> None:
    """AC-3: no skill is emitted for the command-only ``publish`` verb."""
    pg.generate_skills(output_dir=tmp_path)
    assert not (tmp_path / "publish").exists()
    assert not (tmp_path / "publish" / "SKILL.md").exists()


def test_generate_skills_never_overwrites_bespoke(tmp_path) -> None:
    """AC-3: generate_skills iterates SKILL_VERBS only, so a pre-existing bespoke
    skill (run / discuss-feature) is never touched."""
    sentinel = "SENTINEL bespoke body — handwritten, not generated\n"
    for b in ("run", "discuss-feature"):
        d = tmp_path / b
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(sentinel, encoding="utf-8")

    pg.generate_skills(output_dir=tmp_path)

    for b in ("run", "discuss-feature"):
        assert (tmp_path / b / "SKILL.md").read_text(encoding="utf-8") == sentinel


def test_main_regenerates_deleted_skill() -> None:
    """review F-1: deleting a committed skill and running ``main()`` recreates it
    byte-exact — proof that ``main()`` actually calls ``generate_skills``."""
    victim = SKILLS_DIR / "status" / "SKILL.md"
    original = victim.read_bytes()
    victim.unlink()
    try:
        pg.main([])
        assert victim.exists(), "main() did not regenerate the deleted skill"
        assert victim.read_bytes() == original
    finally:
        if not victim.exists() or victim.read_bytes() != original:
            victim.write_bytes(original)


# --------------------------------------------------------------------------
# step-2 — generate_manifest (.claude-plugin/plugin.json)
# --------------------------------------------------------------------------

def test_generate_manifest_byte_exact(tmp_path) -> None:
    """AC-2 / C-003: the generated ``plugin.json`` reproduces the committed
    manifest byte-for-byte (mind the trailing newline)."""
    dest = pg.generate_manifest(output_dir=tmp_path)
    assert dest.read_bytes() == MANIFEST_PATH.read_bytes()


def test_main_regenerates_deleted_manifest() -> None:
    """review F-1: deleting the committed manifest and running ``main()``
    recreates it byte-exact — proof that ``main()`` calls ``generate_manifest``."""
    original = MANIFEST_PATH.read_bytes()
    MANIFEST_PATH.unlink()
    try:
        pg.main([])
        assert MANIFEST_PATH.exists(), "main() did not regenerate the deleted manifest"
        assert MANIFEST_PATH.read_bytes() == original
    finally:
        if not MANIFEST_PATH.exists() or MANIFEST_PATH.read_bytes() != original:
            MANIFEST_PATH.write_bytes(original)


# --------------------------------------------------------------------------
# step-3 — single-source shared verb description (reconcile ack drift)
# --------------------------------------------------------------------------

def _read_desc(md: Path) -> str:
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    raise AssertionError(f"no description: line in {md}")


def test_ack_command_desc_reconciled(tmp_path) -> None:
    """AC-4: the shared verb description is single-sourced from
    ``VERB_SPECS[verb]["short"]``, so regenerating ``commands/ack.md`` yields the
    reconciled text (the stale ``--pick N`` is fixed to ``--pick N or --auto for
    gate-policy``); the command-only ``publish`` keeps its own description."""
    pg._generate_commands(output_dir=tmp_path)

    ack_desc = _read_desc(tmp_path / "ack.md")
    assert ack_desc == pg.VERB_SPECS["ack"]["short"]
    assert "--pick N or --auto for gate-policy" in ack_desc

    publish_desc = _read_desc(tmp_path / "publish.md")
    assert publish_desc == "Publish the review verdict to the ticket's GitHub PR"


# --------------------------------------------------------------------------
# step-6 — document the regen rule + idempotency
# --------------------------------------------------------------------------

def test_regen_rule_documented() -> None:
    """AC-9: the regen rule is stated explicitly in CLAUDE.md and is machine-
    checkable — it names the generator, the trigger (core/agents /
    verb-dictionary), and the drift-guard that enforces it. Assert the specific
    canonical phrase, not an incidental mention (review F-2)."""
    text = (FW / "CLAUDE.md").read_text(encoding="utf-8")
    assert "run `python3 core/skills/plugin_gen.py`" in text
    assert "core/agents" in text
    assert "VERB_SPECS" in text
    assert "test_plugin_agents_in_sync.py" in text


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_plugin_gen_idempotent() -> None:
    """AC-10: running ``main()`` twice is a no-op — the second run produces no
    diff across the whole plugin (agents+commands+skills+manifest stable)."""
    pg.main([])
    before = _snapshot(PLUGIN_DIR)
    pg.main([])
    after = _snapshot(PLUGIN_DIR)
    assert after == before
