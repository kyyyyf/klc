#!/usr/bin/env python3
"""Structural tests for the KLC-079 skill-front (klc-plugin/skills/discuss-feature).

The skill is mostly prose, so the guarantees we can assert mechanically are that
it exists, carries valid frontmatter, documents the exact KLC-077/078 interfaces
verbatim (so it cannot silently drift), and spells out the validate-before-create
discipline this ticket owns.
"""
from __future__ import annotations

import re
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
SKILL = FW_ROOT / "klc-plugin" / "skills" / "discuss-feature" / "SKILL.md"


def _text() -> str:
    assert SKILL.exists(), f"skill missing at {SKILL}"
    return SKILL.read_text(encoding="utf-8")


def test_skill_exists_with_frontmatter():
    text = _text()
    assert text.startswith("---"), "skill must open with YAML frontmatter"
    fm = text.split("---", 2)[1]
    assert re.search(r"^name:\s*\S+", fm, re.MULTILINE), "frontmatter needs a name"
    assert re.search(r"^description:", fm, re.MULTILINE), "frontmatter needs a description"


def test_documents_intake_flags():
    text = _text()
    assert "--epic" in text, "skill must document the --epic flag"
    assert "--blocked-by" in text, "skill must document the --blocked-by flag"
    # the concrete intake invocation must appear
    assert "klc intake" in text


def test_documented_command_includes_description():
    """HIGH-1: the documented intake command must carry a description positional
    (intake hard-fails without one), so the skill never emits a broken argv."""
    text = _text()
    # the fenced command line that ends in a <description> positional
    cmd_lines = [ln for ln in text.splitlines() if "klc intake" in ln and "--epic" in ln]
    assert cmd_lines, "expected a documented `klc intake --epic …` command line"
    assert any("<description>" in ln for ln in cmd_lines), (
        "documented intake command must include the trailing <description> positional"
    )
    # PlannedTicket guidance must mention description as required
    assert "description" in text.lower()


def test_documents_downstream_phase_validation():
    """MEDIUM-1: skill must state it validates the downstream #phase against
    config/phases.yml before create (guarding the no-partial-epic invariant)."""
    text = _text()
    assert "config/phases.yml" in text
    low = text.lower()
    assert "phase" in low and ("partial" in low)


def test_documents_epic_md_persistence():
    """LOW-2: skill must explain epic.md is persisted via the root's state_tx."""
    text = _text()
    assert "state_tx" in text, "must explain epic.md persistence via state_tx"


def test_documents_edge_syntax_matching_doc():
    """Edge syntax must match the shared contract verbatim: <K>@<point>[:cond]#<phase>."""
    text = _text()
    assert "<K>@<point>[:cond]#<phase>" in text, (
        "edge syntax must be documented exactly as in the shared contract"
    )
    # the three points and the v1 condition vocabulary
    for point in ("design-accepted", "integrated", "archived"):
        assert point in text, f"point {point!r} must be documented"
    assert "passed" in text, "the v1 condition 'passed' must be documented"


def test_documents_validate_before_create():
    text = _text().lower()
    assert "cycle" in text, "must mention cycle detection"
    assert "dangling" in text, "must mention dangling-edge detection"
    # ordering: validation happens BEFORE creation
    assert "before" in text and "creat" in text, "must state validate-before-create"


def test_documents_board_epic_view():
    text = _text()
    assert "board --epic" in text, "skill must surface the ready set via board --epic"
    assert "ready set" in text.lower()


def test_writes_epic_md_into_root_ticket():
    text = _text()
    assert "epic.md" in text
    assert ".klc/tickets/<ROOT>/epic.md" in text, (
        "skill must write epic.md into the root ticket's dir"
    )


def test_links_shared_contract_and_helper():
    text = _text()
    assert "docs/20260724_epic_feature_impl_plan.md" in text, "must link the shared contract"
    assert "core/skills/epic_plan.py" in text, "must reference the validation helper"


def test_documents_interactive_principles():
    text = _text().lower()
    assert "one question at a time" in text
    assert "recommendation" in text  # lead with a recommendation
    assert "explore before asking" in text


def test_orchestrate_not_reimplement_discipline():
    text = _text().lower()
    assert "orchestrate" in text
    # references both sibling tickets it depends on
    raw = _text()
    assert "KLC-077" in raw and "KLC-078" in raw
