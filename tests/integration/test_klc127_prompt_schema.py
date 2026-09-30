#!/usr/bin/env python3
"""tests/integration/test_klc127_prompt_schema.py — KLC-127 step-10, AC-11/AC-15
context: the four independent reviewer prompts (spec, test-plan, impl-plan,
drift) show the one Finding shape through ONE shared include
(`core/agents/_includes/finding-schema.md`) plus one line naming the kind's
own closed `rule_name` vocabulary and the D-005 file/line rule, instead of
each carrying its own "Output schema" JSON worked example and Field-rules
list in the old (`category`/`detail`/`suggested_fix`) shape.

Hermetic: every test reads real committed prompt files (source or the
rendered `klc-plugin/agents/` twin) — no tmp_path fixture is needed because
the SUBJECT under test is the shipped prompt text itself, not a stand-in.
`test_the_include_example_validates_through_validate_handback` is the one
test that also drives real code (`handback.validate_handback`) to prove the
include's worked example is not just prose that LOOKS like the shape but
actually IS the shape.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import drift_review as dr  # noqa: E402
import handback as hb  # noqa: E402
import implplan_review as ipr  # noqa: E402
import spec_review as sr  # noqa: E402
import testplan_review as tpr  # noqa: E402
from plugin_gen import expand_includes  # noqa: E402

CORE_AGENTS = FW_ROOT / "core" / "agents"
PLUGIN_AGENTS = FW_ROOT / "klc-plugin" / "agents"
FINDING_SCHEMA = CORE_AGENTS / "_includes" / "finding-schema.md"

# (source filename, handback kind name, the ReviewKind carrying the real
# finding_categories/decision_topics vocabulary for that kind)
_REVIEWERS = (
    ("spec-reviewer.md", "spec", sr.SPEC_REVIEW),
    ("test-plan-reviewer.md", "test-plan", tpr.TEST_PLAN_REVIEW),
    ("impl-plan-reviewer.md", "impl-plan", ipr.IMPL_PLAN_REVIEW),
    ("drift-reviewer.md", "drift", dr.DRIFT_CHECK),
)

_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
_ENUM_RE = re.compile(r"`rule_name`\s*∈\s*`([^`]+)`")

# A targeted pattern on JSON keys / field-list tokens, not a whole-word ban —
# `category`/`detail` are common English words that may legitimately appear
# in prose elsewhere in these files.
_OLD_FIELD_RE = re.compile(
    r'"category"\s*:|"detail"\s*:|"suggested_fix"\s*:'
    r"|`category`|`detail`|`suggested_fix`"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# the include itself
# ---------------------------------------------------------------------------

def test_finding_schema_include_is_at_most_1300_bytes():
    """AC-11: the include shared by all four reviewers is capped at 1,300
    bytes — duplicating it into four prompts must stay cheap against the
    byte budget (F-011/F-012)."""
    assert FINDING_SCHEMA.is_file(), "core/agents/_includes/finding-schema.md must exist"
    size = len(FINDING_SCHEMA.read_bytes())
    assert size <= 1300, f"finding-schema.md is {size} bytes, over the 1300 cap (AC-11)"


def _include_example_doc(rule_name: str, topic: str) -> dict:
    text = _read(FINDING_SCHEMA)
    m = _JSON_BLOCK_RE.search(text)
    assert m, "finding-schema.md must carry exactly one fenced json worked example"
    raw = m.group(1).replace("RULE", rule_name).replace("TOPIC", topic)
    return json.loads(raw)


@pytest.mark.parametrize("kind_name,ref_kind", [(n, rk) for _, n, rk in _REVIEWERS])
def test_the_include_example_validates_through_validate_handback(kind_name, ref_kind):
    """AC-11: the include's example is kind-neutral (`RULE`/`TOPIC`
    placeholders); substituting each kind's own first real vocabulary value
    for the placeholder must validate CLEAN through the real
    `handback.validate_handback` for all four independent kinds — proves the
    shape itself, not just prose that resembles it."""
    doc = _include_example_doc(ref_kind.finding_categories[0], ref_kind.decision_topics[0])
    errors = hb.validate_handback(kind_name, doc)
    assert errors == [], errors


# ---------------------------------------------------------------------------
# the four reviewer prompts (source) carry the include line
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,kind_name,ref_kind", _REVIEWERS)
def test_the_four_independent_reviewer_prompts_carry_the_include_line(
        filename, kind_name, ref_kind):
    """AC-11: each of the four independent reviewer prompts carries the
    literal `{{include:finding-schema}}` directive — this fails until the
    reviewer's Output-schema section is rewritten to use it."""
    text = _read(CORE_AGENTS / filename)
    assert "{{include:finding-schema}}" in text, (
        f"{filename} must carry the literal {{{{include:finding-schema}}}} line"
    )


# ---------------------------------------------------------------------------
# each prompt names EXACTLY its own kind's rule_name vocabulary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,kind_name,ref_kind", _REVIEWERS)
def test_each_prompt_names_exactly_its_kinds_rule_name_vocabulary(
        filename, kind_name, ref_kind):
    """AC-11 (closed-world honesty): read the RENDERED `klc-plugin/agents/`
    twin — what the reviewer actually receives — and check its declared
    `rule_name` ∈ `a | b | c` enumeration against the REAL `ReviewKind`
    vocabulary; no invented rule_name slips in and none is missing."""
    text = _read(PLUGIN_AGENTS / filename)
    m = _ENUM_RE.search(text)
    assert m, f"{filename} (rendered) must carry a `rule_name` ∈ `...` enumeration line"
    declared = {tok.strip() for tok in m.group(1).split("|") if tok.strip()}
    assert declared == set(ref_kind.finding_categories), (
        f"{filename}: declared rule_name vocabulary {declared} must equal "
        f"{set(ref_kind.finding_categories)}"
    )


# ---------------------------------------------------------------------------
# no prompt still names the old independent-shape fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,kind_name,ref_kind", _REVIEWERS)
def test_no_prompt_names_category_detail_or_suggested_fix_as_a_finding_field(
        filename, kind_name, ref_kind):
    """AC-11: none of the four reviewer prompts still mentions `category`,
    `detail` or `suggested_fix` as a finding field (a targeted JSON-key /
    backtick-field pattern, not a whole-word ban on common English words)."""
    text = _read(CORE_AGENTS / filename)
    hits = _OLD_FIELD_RE.findall(text)
    assert not hits, f"{filename} still names an old-shape finding field: {hits}"


# ---------------------------------------------------------------------------
# the rendered twins carry the expanded include, never a literal directive
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,kind_name,ref_kind", _REVIEWERS)
def test_rendered_twins_carry_the_expanded_include_and_no_literal_directive(
        filename, kind_name, ref_kind):
    """AC-11/AC-16 context: the rendered `klc-plugin/agents/` twin carries
    the include's EXPANDED body (what the reviewer actually reads) and no
    literal `{{include:` directive string anywhere."""
    rendered = _read(PLUGIN_AGENTS / filename)
    assert "{{include:" not in rendered, (
        f"{filename} (rendered) still carries a literal include directive — "
        f"run python3 core/skills/plugin_gen.py"
    )
    expanded_source = expand_includes(_read(CORE_AGENTS / filename))
    include_body = _read(FINDING_SCHEMA).rstrip("\n")
    assert include_body in expanded_source, (
        "expand_includes must inline the finding-schema body verbatim"
    )
    assert include_body in rendered, (
        f"{filename} (rendered) must carry the finding-schema include's expanded body"
    )
