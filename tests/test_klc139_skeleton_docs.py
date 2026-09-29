"""KLC-139 step-7/step-8 — `docs/architecture.md` documents `klc skeleton`
(AC-11), including the three new refusal reasons step-8's review-fix round
added (D-8-1: `cannot read file`, `not valid UTF-8`, `too deeply nested to
parse`), in their real ladder position.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_architecture_doc_has_skeleton_section_with_required_tokens():
    """AC-11 (step-7) + D-8-1 (step-8, operator-confirmed): the section
    heading that contains `klc skeleton`, sliced to the next `## ` heading
    (or EOF), carries every required literal token, including step-8's
    three new refusal reasons."""
    text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and "klc skeleton" in line:
            start = i
            break
    assert start is not None, "no '## ...klc skeleton...' heading found"

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    section = "\n".join(lines[start:end])

    required = [
        "klc skeleton",
        "skeleton.max_fields",
        "skeleton.max_line",
        "skeleton.max_bytes",
        "[truncated]",
        "never stored",
        "rule-scoped",
        "inventory.json",
        "cannot read file",
        "not valid UTF-8",
        "too deeply nested to parse",
    ]
    for token in required:
        assert token in section, f"missing token {token!r} in the skeleton section"
