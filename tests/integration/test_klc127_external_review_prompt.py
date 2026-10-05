#!/usr/bin/env python3
"""tests/integration/test_klc127_external_review_prompt.py — KLC-127 step-11,
AC-12: the external reviewer template asks the external model for the one
Finding shape (filled from `core/agents/_includes/finding-schema.md` at
render time) instead of "Output in markdown format", and
`core/agents/external-review.md` parses that object instead of
`### [SEVERITY] ...` markdown headings, names
`handback.py take --kind external-review` as its intake step, and keeps its
step-5 summary block byte-identical to `main`.

Hermetic: every test reads real committed files or renders the real
`core/templates/external-review-prompt.j2` through a scratch Jinja2
environment with a minimal, in-memory context — no tmp_path fixture reads
or writes the live `.klc/`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import handback as hb  # noqa: E402

TEMPLATE_PATH = FW_ROOT / "core" / "templates" / "external-review-prompt.j2"
EXTERNAL_MD = FW_ROOT / "core" / "agents" / "external-review.md"
PLUGIN_EXTERNAL_MD = FW_ROOT / "klc-plugin" / "agents" / "external-review.md"
FINDING_SCHEMA = FW_ROOT / "core" / "agents" / "_includes" / "finding-schema.md"

# The step-5 block as it stands on `main` 7f2f22e3 (git show main:core/agents/
# external-review.md), captured 2026-09-30 — AC-12's "keeps its step-5 summary
# line unchanged" clause is a literal byte-for-byte pin, not a description.
_STEP5_MAIN_LITERAL = (
    "### 5. Return result\n"
    "Stdout must end with a single JSON line that the orchestrator merges:\n"
    "\n"
    "```json\n"
    "{\n"
    '  "provider": "<resolved>",\n'
    '  "model":    "<resolved>",\n'
    '  "total":    7,\n'
    '  "blocking": 2,\n'
    '  "notes":    "<one-sentence summary>",\n'
    '  "path":     ".klc/reports/external-review-2026-05-04-10-15.md"\n'
    "}\n"
    "```\n"
    "\n"
    "Final signal line:\n"
    "\n"
    "```\n"
    "EXTERNAL_REVIEW_OK\n"
    "```\n"
    "\n"
    "or, on skip:\n"
    "\n"
    "```\n"
    "EXTERNAL_REVIEW_SKIPPED <reason>\n"
    "```\n"
    "\n"
)


def _render_template(finding_schema=None) -> str:
    """Render the real `.j2` template with a minimal context, Jinja2 directly
    (there is no framework renderer for this specific template — it is
    rendered by the reviewer's own judgment at 'Build the prompt', per
    `external-review.md`'s step 1). `StrictUndefined` so a missing variable
    raises rather than silently rendering empty (AC-12's fail-closed half)."""
    from jinja2 import Environment, StrictUndefined
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    tpl = env.from_string(TEMPLATE_PATH.read_text(encoding="utf-8"))
    ctx = dict(context="the shared context",
              focus_areas=["security", "architecture"])
    if finding_schema is not None:
        ctx["finding_schema"] = finding_schema
    return tpl.render(**ctx)


def test_template_asks_for_the_one_shape_json_object_not_markdown():
    """AC-12: the rendered template carries the finding-schema JSON shape
    (filled from the include at render time) and no longer says
    'Output in markdown format'."""
    rendered = _render_template(finding_schema=FINDING_SCHEMA.read_text(encoding="utf-8"))
    assert "Output in markdown format" not in rendered
    assert '"findings"' in rendered and '"decisions_to_confirm"' in rendered
    assert "rule_name" in rendered


def test_template_render_fails_closed_without_the_schema_variable():
    """AC-12 (fail-closed): rendering the template WITHOUT the
    `finding_schema` variable raises — a missing schema must never ship as
    a silently empty section in a dispatched external-review prompt."""
    from jinja2 import UndefinedError
    with pytest.raises(UndefinedError):
        _render_template(finding_schema=None)


@pytest.mark.parametrize("path", [EXTERNAL_MD, PLUGIN_EXTERNAL_MD])
def test_external_review_md_step_3_parses_the_json_object(path):
    """AC-12: both the source and the rendered plugin twin parse the
    one-shape JSON object in place of `### [SEVERITY] ...` markdown
    headings."""
    text = path.read_text(encoding="utf-8")
    assert "### [SEVERITY]" not in text, (
        f"{path} still describes the old `### [SEVERITY]` heading parse rule"
    )
    assert "findings" in text and "decisions_to_confirm" in text


@pytest.mark.parametrize("path", [EXTERNAL_MD, PLUGIN_EXTERNAL_MD])
def test_external_review_md_names_the_intake_command(path):
    """AC-12: both twins name `handback.py take --kind external-review` as
    the intake step for a valid external-review verdict."""
    text = path.read_text(encoding="utf-8")
    assert "handback.py take" in text and "--kind external-review" in text


def test_external_review_md_step_5_block_is_unchanged():
    """AC-12's explicit 'keeps its step-5 summary line unchanged' clause: the
    entire `### 5. Return result` block (through the skip-signal fence) is
    byte-identical to `git show main:core/agents/external-review.md`
    (main 7f2f22e3, captured 2026-09-30)."""
    text = EXTERNAL_MD.read_text(encoding="utf-8")
    idx = text.find("### 5. Return result")
    assert idx != -1, "external-review.md must still carry a step 5"
    end = text.find("{{include:completion-signal}}", idx)
    assert end != -1
    actual = text[idx:end]
    assert actual == _STEP5_MAIN_LITERAL, (
        "the step-5 block changed; AC-12 requires it byte-identical to main"
    )


def test_a_fixture_reply_parses_through_handback_extract_verdict():
    """AC-12: a realistic external-model reply (the one-shape JSON object,
    possibly with narrative before it, as a real model would answer) parses
    cleanly through the real `handback.extract_verdict` — proving the
    CONTRACT, not just the prose that describes it."""
    reply = (
        "Here is my review of the diff.\n\n"
        "```json\n"
        '{"findings": [{"id": "F-1", "rule_name": "missing-null-check", '
        '"severity": "HIGH", "file": "core/skills/foo.py", "line": 42, '
        '"title": "Unchecked None access", "body": "foo() may return None; '
        'the caller dereferences it unconditionally.", '
        '"fix": "Guard the None case before use."}], '
        '"decisions_to_confirm": []}\n'
        "```\n"
    )
    doc = hb.extract_verdict(reply)
    assert doc is not None
    assert doc["findings"][0]["rule_name"] == "missing-null-check"
    errors = hb.validate_handback("external-review", doc)
    assert errors == [], errors
