#!/usr/bin/env python3
"""tests/test_klc127_claude_md_reviewer_paragraph.py — KLC-127 step-11, AC-13:
the code-reviewer paragraph of `CLAUDE.md` asks for the answer as the one
Finding shape and names `python3 core/skills/handback.py take --kind
code-review` as the intake step, changed by AT MOST two lines against
`main`; `core/agents/review.md` (and its plugin twin) repeat the same rule
and tell the orchestrator to render `review-report.md`'s findings table
from `review/findings-pool.json`.

Hermetic: no git subprocess call — the `main` literal below was captured
with `git show main:CLAUDE.md` at 7f2f22e3 on 2026-09-30 (the operator's
Q-004 ack base) and is pinned as a plain string, not derived at test time.
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

CLAUDE_MD = FW_ROOT / "CLAUDE.md"
REVIEW_MD = FW_ROOT / "core" / "agents" / "review.md"
PLUGIN_REVIEW_MD = FW_ROOT / "klc-plugin" / "agents" / "review.md"

# The mandatory-code-reviewer paragraph as it stood on `main` 7f2f22e3,
# captured 2026-09-30 (`git show main:CLAUDE.md`, lines 11-47) — the literal
# AC-13's own diff-count test compares against.
_PARAGRAPH_MAIN_LITERAL = '''## Mandatory: external code review subagent before review-report

When implementing a KLC ticket and writing the review-report, **always** launch
a fresh (non-fork) code-reviewer subagent before writing `review-report.md`.

**Why**: internal review suffers from confirmation bias — the implementer knows
the intent and validates against ACs as written, not against the full codebase.
A fresh subagent catches cross-file gaps (e.g. a file was omitted from scope)
and intra-file contradictions introduced during build. KLC-035 through KLC-037
all had Codex findings that internal review missed for exactly this reason.

**How**:

```
Agent({
  subagent_type: "code-reviewer",   # fresh, no conversation context
  prompt: """
    Review the changes on branch <branch-name> for ticket <KEY>.
    Spec ACs: <paste from spec.md>
    Changed files: <git diff --name-only main..HEAD>

    Read each changed file in full. Check:
    1. Every AC is satisfied in code/prompts/tests.
    2. No related file was missed (e.g. if design.md got a rule, do other
       agent prompts for the same task also need it?).
    3. No intra-file contradictions introduced by the new additions.
    4. Tests cover the new behaviour (not just happy-path).

    Return: findings (severity HIGH/MEDIUM/LOW + description + suggested fix).
    Return empty list if none.
  """
})
```

Wait for the result before writing `review-report.md`. Assess each finding
(fix / won't fix + reason) and document the assessment in the report.
'''


def _current_paragraph() -> str:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    start = text.index("## Mandatory: external code review subagent before review-report")
    end = text.index("**Do not skip this step", start)
    return text[start:end]


def test_claude_md_reviewer_paragraph_asks_for_the_one_shape_and_names_the_intake_command():
    """AC-13: the paragraph now asks for the one-shape JSON object (findings[]
    of Finding records) and names the real intake command."""
    para = _current_paragraph()
    assert '"findings"' in para, "paragraph must ask for the one-shape JSON object"
    assert "rule_name" in para, "paragraph must name a real Finding field"
    assert "python3 core/skills/handback.py take --kind code-review" in para, (
        "paragraph must name the real intake command"
    )


def test_claude_md_paragraph_changed_by_at_most_two_lines():
    """AC-13: the paragraph is changed by AT MOST two lines against `main` —
    a real difflib line-count, not a description of the intent."""
    old_lines = _PARAGRAPH_MAIN_LITERAL.rstrip("\n").splitlines()
    new_lines = _current_paragraph().rstrip("\n").splitlines()
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    changed = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
        if tag != "equal"
    )
    assert changed <= 2, (
        f"CLAUDE.md's code-reviewer paragraph changed by {changed} lines, "
        f"over the 2-line cap (AC-13)"
    )
    # And it DID change (not a no-op edit that trivially satisfies "<= 2").
    assert changed >= 1


@pytest.mark.parametrize("path", [REVIEW_MD, PLUGIN_REVIEW_MD])
def test_review_md_repeats_the_rule_and_names_the_pool_as_the_report_source(path):
    """AC-13: `core/agents/review.md` (and its rendered plugin twin) repeat
    the one-shape rule and tell the orchestrator to render the findings
    table from `review/findings-pool.json`, not the two separate
    `*-findings.json` files directly."""
    text = path.read_text(encoding="utf-8")
    assert "handback.py take" in text and "--kind code-review" in text
    assert "findings.py pool" in text
    assert "review/findings-pool.json" in text
