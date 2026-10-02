"""tests/integration/test_klc154_md_rewrite.py — KLC-154 step-1, AC-3: the
`.md` rewrite keeps every byte outside the verdict JSON span identical and
`decisions_to_confirm` equal as parsed JSON, and keeps the original layout
style (one-line stays one-line, a multi-line block is re-written with
indent=2, and a CRLF file's new span uses `\\r\\n` like the original).
D-003: when the LAST fenced JSON block has neither `findings` nor
`decisions_to_confirm`, the file is left alone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


@pytest.mark.parametrize("variant", ["multi-line", "one-line", "json-example-above", "crlf"])
def test_md_rewrite_keeps_narrative_byte_identical(variant):
    """AC-3/D-004: migrating a `.md` verdict keeps every byte outside the
    JSON span identical, `decisions_to_confirm` parses equal, and the
    chosen layout style survives."""
    old = [{"id": "F-1", "category": "infidelity", "severity": "high",
           "detail": "a real finding", "ref": "", "suggested_fix": None}]
    decisions = [{"id": "D-1", "topic": "scope", "question": "q?", "recommended": "yes"}]

    narrative = "Some narrative text before the verdict.\n\nMore narrative.\n"
    if variant == "json-example-above":
        narrative += '```json\n{"example": true}\n```\n'
    one_line = variant == "one-line"
    newline = "\r\n" if variant == "crlf" else "\n"

    text = support.verdict_md(old, decisions, narrative=narrative,
                              one_line=one_line, newline=newline)

    span_before = findings_migrate._verdict_span(text)
    assert span_before is not None
    a, b, _ = span_before

    result = findings_migrate.rewrite_md_block(text, "spec")
    assert result is not None
    new_text, old_findings, new_findings = result

    assert new_text.startswith(text[:a])
    assert new_text.endswith(text[b:])
    assert old_findings == old
    assert not any(findings_migrate.is_old(r) for r in new_findings)

    new_span = findings_migrate._verdict_span(new_text)
    assert new_span is not None
    na, nb, new_doc = new_span
    assert new_doc["decisions_to_confirm"] == decisions

    new_json_text = new_text[na:nb]
    if one_line:
        assert "\n" not in new_json_text
    else:
        assert "\n" in new_json_text.replace("\r\n", "\n") or "\r\n" in new_json_text
    if variant == "crlf":
        assert "\r\n" in new_json_text
        assert new_json_text.replace("\r\n", "").count("\n") == 0


def test_last_block_without_verdict_keys_is_left_alone():
    """D-003: when the LAST fenced JSON block has neither `findings` nor
    `decisions_to_confirm`, the file is left alone — mirrors
    `spec_review._extract_json`'s own "last candidate wins" rule, which
    never falls back to an earlier block."""
    earlier_verdict = json.dumps({"findings": support.old_independent(1),
                                 "decisions_to_confirm": []})
    text = (f"Some narrative.\n```json\n{earlier_verdict}\n```\n"
           "More narrative after.\n```json\n{\"phase\": \"build\", \"signal\": \"done\"}\n```\n")
    result = findings_migrate.rewrite_md_block(text, "spec")
    assert result is None
