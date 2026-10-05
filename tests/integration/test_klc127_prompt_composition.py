#!/usr/bin/env python3
"""tests/integration/test_klc127_prompt_composition.py — KLC-127 step-11,
AC-16: `runner._compose_prompt` expands every `{{include:...}}` line for the
headless dispatch path, and every in-client spawn instruction names the
RENDERED `klc-plugin/agents/<reviewer>.md` file — never the raw
`core/agents/<reviewer>.md` source, which still carries a literal
`{{include:...}}` directive a subagent cannot resolve on its own.

Hermetic: every test drives the real `runner._compose_prompt` /
`plugin_gen.expand_includes` over either a `tmp_path` fixture prompt or the
real committed `core/agents/external-review.md` (read-only); no test
launches `claude` or touches the live `.klc/`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import runner  # noqa: E402

CORE_AGENTS = FW_ROOT / "core" / "agents"

# (doc file, the reviewer .md name(s) it spawns) — AC-16's own named readers.
_SPAWN_DOCS = (
    ("discovery.md", ("spec-reviewer.md",)),
    ("discovery-lite.md", ("spec-reviewer.md", "impl-plan-reviewer.md")),
    ("design.md", ("impl-plan-reviewer.md",)),
    ("test-planner.md", ("test-plan-reviewer.md",)),
    ("review.md", ("drift-reviewer.md", "external-review.md")),
)


def test_compose_prompt_expands_every_include_line(tmp_path):
    """AC-16: a fixture prompt carrying `{{include:finding-schema}}` composes
    with the include fully expanded — no literal `{{include:` substring
    survives."""
    prompt = tmp_path / "fixture-reviewer.md"
    prompt.write_text(
        "# Fixture reviewer\n\n{{include:finding-schema}}\n\nDo the review.\n",
        encoding="utf-8",
    )
    composed = runner._compose_prompt(prompt, None)
    assert "{{include:" not in composed
    assert "rule_name" in composed  # the include's body actually landed


def test_composed_external_review_prompt_has_no_literal_include_line():
    """AC-16: the real `core/agents/external-review.md`, composed through
    `runner._compose_prompt` (the headless dispatch route named in F-012),
    is fully expanded — the exact reviewer named in the AC's own
    verification method."""
    composed = runner._compose_prompt(CORE_AGENTS / "external-review.md", None)
    assert "{{include:" not in composed
    assert "run_signal" in composed or "COMPLETION SIGNAL" in composed.upper()


def test_compose_prompt_fails_closed_on_an_unresolvable_include(tmp_path):
    """AC-16 (fail-closed): a prompt naming an include that does not exist
    raises rather than silently shipping the literal directive to a
    dispatched subagent."""
    prompt = tmp_path / "broken-reviewer.md"
    prompt.write_text("{{include:does-not-exist}}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        runner._compose_prompt(prompt, None)


@pytest.mark.parametrize("doc_name,reviewers", _SPAWN_DOCS)
def test_inclient_spawn_instructions_name_the_rendered_plugin_path_not_the_raw_source(
        doc_name, reviewers):
    """AC-16: each reviewer-spawn instruction in the named in-client
    orchestrator prompts now names `klc-plugin/agents/<reviewer>.md` — what
    the dispatcher actually hands the subagent — not the raw
    `core/agents/<reviewer>.md` source, which still carries an unresolved
    `{{include:...}}` line."""
    text = (CORE_AGENTS / doc_name).read_text(encoding="utf-8")
    for reviewer_name in reviewers:
        # KLC-172 step-4: producer prompts no longer describe the downstream
        # reviewer spawn, so only review.md must still name the rendered path;
        # every doc must never point at the raw source.
        if doc_name == "review.md":
            assert f"klc-plugin/agents/{reviewer_name}" in text, (
                f"{doc_name} must name klc-plugin/agents/{reviewer_name} as the "
                f"rendered prompt handed to the subagent"
            )
        assert f"`core/agents/{reviewer_name}`" not in text, (
            f"{doc_name} must not still point the in-client spawn at the raw "
            f"core/agents/{reviewer_name} source"
        )


def test_docs_process_spawn_instructions_name_the_rendered_plugin_path():
    """AC-16: `docs/process.md`'s spec-reviewer and impl-plan-reviewer spawn
    mentions also name the rendered `klc-plugin/agents/` path."""
    text = (FW_ROOT / "docs" / "process.md").read_text(encoding="utf-8")
    assert "klc-plugin/agents/spec-reviewer.md" in text
    assert "klc-plugin/agents/impl-plan-reviewer.md" in text
    assert "`core/agents/spec-reviewer.md`" not in text
    assert "`core/agents/impl-plan-reviewer.md`" not in text
