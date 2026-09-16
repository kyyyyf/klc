#!/usr/bin/env python3
"""tests/test_klc113_includes.py — KLC-113 include-expansion mechanism.

Step-1 (AC-1, AC-15/C-002 regression):
    test_generate_agents_expands_include_directive
    test_unresolvable_include_raises
    test_include_body_is_not_recursively_expanded
    test_precommit_gate_fires_on_includes_dir_changes

Step-2 (AC-3, AC-4) and step-3 (AC-5) tests are added by their own steps.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

FW = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW))

import plugin_gen as pg  # noqa: E402


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --- step-1: AC-1 -------------------------------------------------------------

def test_generate_agents_expands_include_directive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        agents_src = t / "core" / "agents"
        includes_dir = agents_src / "_includes"
        _write(agents_src / "fixture-phase.md",
               "# Fixture phase\n\nBody text.\n\n{{include:greeting}}\n\nMore body.\n")
        _write(includes_dir / "greeting.md", "Hello from the include.")

        text = (agents_src / "fixture-phase.md").read_text(encoding="utf-8")
        expanded = pg.expand_includes(text, includes_dir=includes_dir)

        assert "Hello from the include." in expanded
        assert "{{include:greeting}}" not in expanded


def test_unresolvable_include_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        includes_dir = t / "_includes"
        includes_dir.mkdir(parents=True, exist_ok=True)
        text = "# Fixture\n\n{{include:does-not-exist}}\n"
        try:
            pg.expand_includes(text, includes_dir=includes_dir)
        except ValueError as e:
            assert "does-not-exist" in str(e)
        else:
            raise AssertionError("expand_includes should have raised ValueError")


def test_include_body_is_not_recursively_expanded() -> None:
    """A directive inside an include's own body is left as literal text — the
    expander is a single non-recursive substitution pass (D-001)."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        includes_dir = t / "_includes"
        _write(includes_dir / "outer.md",
               "Outer body with a literal directive: {{include:inner}}")
        _write(includes_dir / "inner.md", "Inner body — should not appear.")

        text = "# Fixture\n\n{{include:outer}}\n"
        expanded = pg.expand_includes(text, includes_dir=includes_dir)

        assert "Outer body with a literal directive: {{include:inner}}" in expanded
        assert "Inner body — should not appear." not in expanded


# --- step-1: AC-15 / C-002 regression -----------------------------------------

def test_precommit_gate_fires_on_includes_dir_changes() -> None:
    """The pre-commit `--check-if-staged` gate must fire on a change confined to
    `core/agents/_includes/`, not just to the top-level `core/agents/*.md`
    files (C-002)."""
    assert pg.plugin_sources_staged(
        ["core/agents/_includes/completion-signal.md"]
    ) is True


# --- step-2: AC-3, AC-4 --------------------------------------------------------

AGENTS_DIR = FW / "core" / "agents"


def test_completion_signal_heading_appears_once_as_literal() -> None:
    """The literal heading text must appear in zero `core/agents/*.md` source
    files — it lives only in the include body."""
    hits = [
        md.name for md in AGENTS_DIR.glob("*.md")
        if "## Completion signal (orchestrator)" in md.read_text(encoding="utf-8")
    ]
    assert hits == []


def test_impl_md_has_one_findings_assessment_procedure() -> None:
    text = (AGENTS_DIR / "impl.md").read_text(encoding="utf-8")
    assert "{{include:review-findings-assessment}}" in text
    for heading in (
        "### spec-review findings",
        "### test-plan-review findings",
        "### impl-plan-review findings",
    ):
        assert heading not in text, heading


def test_completion_signal_include_size_and_content() -> None:
    include = AGENTS_DIR / "_includes" / "completion-signal.md"
    data = include.read_bytes()
    assert len(data) <= 500, f"{len(data)} bytes, over the 500-byte cap (AC-4)"
    text = data.decode("utf-8")
    assert '"phase"' in text and '"signal"' in text and '"artifacts"' in text
    assert '"next_action"' in text
    assert "```json" in text  # one worked example block


# --- step-3: AC-5 ---------------------------------------------------------------

_BANNED = (
    "MODEL_SWITCH_REQUIRED", "MODEL_NOTE",
    "## Model handoff guard", "## Model note",
)


def test_no_model_switch_prose_anywhere() -> None:
    roots = [FW / "core" / "agents", FW / "klc-plugin" / "agents"]
    hits = [
        f"{md}: {tok}"
        for root in roots for md in root.rglob("*.md")
        for tok in _BANNED if tok in md.read_text(encoding="utf-8")
    ]
    assert hits == [], hits
