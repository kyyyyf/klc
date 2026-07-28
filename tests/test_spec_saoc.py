#!/usr/bin/env python3
"""Tests for core/skills/spec_saoc.py — the SAOC acceptance-criterion format."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import spec_saoc as saoc  # noqa: E402


# --- recognition -------------------------------------------------------------

def test_parses_numbered_ac_line():
    ac = saoc.parse_ac_line("1. AC-1: the parser · rejects · a malformed AC · when parts != 4")
    assert ac is not None
    assert ac.id == "AC-1"
    assert ac.subject == "the parser"
    assert ac.action == "rejects"
    assert ac.object == "a malformed AC"
    assert ac.condition == "when parts != 4"
    assert ac.is_wellformed


def test_parses_checklist_ac_line():
    ac = saoc.parse_ac_line("- [ ] AC-2: the gate · surfaces · an open marker · when [NEEDS CLARIFICATION] remains")
    assert ac is not None and ac.id == "AC-2" and ac.is_wellformed


def test_parses_bare_ac_line():
    ac = saoc.parse_ac_line("AC-3: the reader · loads · the constitution · when the file exists")
    assert ac is not None and ac.is_wellformed


def test_non_ac_line_is_none():
    assert saoc.parse_ac_line("This is just prose about ACs.") is None
    assert saoc.parse_ac_line("## Acceptance Criteria") is None


# --- validation --------------------------------------------------------------

def test_wellformed_requires_exactly_four_parts():
    three = saoc.parse_ac_line("AC-1: subject · action · object")
    assert not three.is_wellformed
    assert "condition" in three.missing_parts()


def test_empty_segment_is_missing():
    ac = saoc.parse_ac_line("AC-1: subject ·  · object · condition here")
    assert not ac.is_wellformed
    assert "action" in ac.missing_parts()


def test_too_many_segments_flagged():
    ac = saoc.parse_ac_line("AC-1: a · b · c · d · e")
    assert not ac.is_wellformed
    assert any(p.startswith("extra-segments") for p in ac.missing_parts())


def test_no_separator_is_malformed():
    ac = saoc.parse_ac_line("AC-1: given X when Y then Z")
    assert not ac.is_wellformed
    # Only the subject slot is filled; the other three are missing.
    assert set(ac.missing_parts()) >= {"action", "object", "condition"}


def test_parse_acs_multiple_and_order():
    text = (
        "## Acceptance Criteria\n"
        "1. AC-1: s1 · a1 · o1 · c1 here\n"
        "2. AC-2: s2 · a2 · o2 · c2 here\n"
    )
    acs = saoc.parse_acs(text)
    assert [a.id for a in acs] == ["AC-1", "AC-2"]
    assert all(a.is_wellformed for a in acs)


def test_malformed_helper_filters():
    text = "AC-1: s · a · o · condition ok here\nAC-2: incomplete only\n"
    bad = saoc.malformed(text)
    assert [a.id for a in bad] == ["AC-2"]


# --- testability heuristic ---------------------------------------------------

def test_weak_condition_flags_vague_terms():
    assert saoc.weak_condition("when it works correctly")
    assert saoc.weak_condition("when the output is reasonable")


def test_weak_condition_flags_too_short():
    assert saoc.weak_condition("ok")


def test_weak_condition_accepts_verifiable():
    assert saoc.weak_condition("when the segment count is not exactly 4") is None
    assert saoc.weak_condition("then the exit code equals 1") is None


# --- Unicode separator normalization + middot-inside-a-part limitation --------

def test_lookalike_separators_normalized():
    # An AC typed with BULLET, DOT OPERATOR, or KATAKANA MIDDLE DOT still parses
    # as four parts rather than being scored malformed.
    for sep in ("•", "⋅", "・"):
        ac = saoc.parse_ac_line(f"AC-1: subject {sep} action {sep} object {sep} condition here")
        assert ac.is_wellformed, f"separator {sep!r} not normalized"
        assert ac.subject == "subject" and ac.condition == "condition here"


def test_greek_ano_teleia_separator_normalized():
    # U+0387 GREEK ANO TELEIA is a distinct codepoint from U+00B7 that renders
    # identically; an AC using it as the separator must still parse well-formed.
    sep = "\u0387"
    assert sep != "\u00b7" and ord(sep) == 0x387
    ac = saoc.parse_ac_line(f"AC-1: subject {sep} action {sep} object {sep} condition here")
    assert ac.is_wellformed
    assert ac.action == "action" and ac.condition == "condition here"


def test_middot_inside_a_part_over_splits():
    # Documented limitation (no escaping): a literal middle dot inside a part
    # over-splits, so the AC is flagged malformed. Guards the documented behavior.
    ac = saoc.parse_ac_line("AC-1: the a·b module · runs · the job · when invoked now")
    assert not ac.is_wellformed
    assert any(p.startswith("extra-segments") for p in ac.missing_parts())
