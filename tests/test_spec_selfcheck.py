#!/usr/bin/env python3
"""Tests for core/skills/spec_selfcheck.py — the deterministic spec self-check gate.

Covers each dimension, the 083-deterministic vs 084-surfaced split, track
scaling (XS light vs M full), reuse of the KLC-082 constitution reader, and the
degrade-not-fail path when the constitution is unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import spec_selfcheck as sc  # noqa: E402
import constitution as con  # noqa: E402


def _dims(report):
    return {f.dimension for f in report.findings}


_GOOD_SPEC = """\
---
ticket: KLC-XXX
kind: feature
authority: agent
risk_tags: []
---

## Goals
Provide a deterministic gate that checks the acceptance criteria of a spec.

## Acceptance Criteria
1. AC-1: the gate · rejects · a spec whose AC is not in SAOC form · when a segment is missing
2. AC-2: the reader · surfaces · the constitution checklist · when the file is present

## Estimate
total: 4
"""


# --- format: non-SAOC is SURFACE, duplicate id is BLOCK ---------------------

def test_non_saoc_ac_surfaced_not_blocked():
    # A legacy (pre-SAOC) AC is surfaced as a warning, never a hard fail.
    spec = _GOOD_SPEC.replace(
        "1. AC-1: the gate · rejects · a spec whose AC is not in SAOC form · when a segment is missing",
        "1. AC-1: given X when Y then Z",
    )
    rep = sc.self_check(spec, "M")
    assert rep.ok  # format no longer blocks
    assert any(f.dimension == "format" and f.ref == "AC-1" for f in rep.surfaced)


def test_no_acs_surfaced_not_blocked():
    spec = "## Goals\nDo a thing.\n\n## Acceptance Criteria\n(none yet)\n"
    rep = sc.self_check(spec, "M")
    assert rep.ok
    assert any(f.dimension == "format" for f in rep.surfaced)


def test_duplicate_ac_id_blocks():
    spec = _GOOD_SPEC.replace(
        "2. AC-2: the reader · surfaces · the constitution checklist · when the file is present",
        "2. AC-1: the reader · surfaces · the checklist · when the file is present",
    )
    rep = sc.self_check(spec, "M")
    assert not rep.ok
    assert any(f.dimension == "format" and "duplicate" in f.message for f in rep.blocking)


def test_good_spec_passes_format():
    rep = sc.self_check(_GOOD_SPEC, "M")
    assert not any(f.dimension == "format" for f in rep.findings)


# --- markers (deterministic, BLOCK) -----------------------------------------

def test_open_marker_surfaced_as_block():
    spec = _GOOD_SPEC.replace(
        "## Estimate",
        "## Open questions\n[NEEDS CLARIFICATION: which track floor applies?]\n\n## Estimate",
    )
    rep = sc.self_check(spec, "M")
    assert not rep.ok
    assert any(f.dimension == "markers" for f in rep.blocking)


def test_unresolved_markers_ignores_code_examples():
    text = "See `[NEEDS CLARIFICATION: x]` in a code span.\n```\n[NEEDS CLARIFICATION: y]\n```\n"
    assert sc.unresolved_markers(text) == []


def test_unresolved_markers_reports_open_one():
    text = "## Acceptance Criteria\n- [ ] AC-1: s · a · o [NEEDS CLARIFICATION: real question] · c here\n"
    assert sc.unresolved_markers(text)


def test_unresolved_markers_ignores_tilde_and_indented_code():
    # ~~~ fences and 4-space-indented code blocks are code too; example markers
    # inside them must NOT trip the check.
    text = (
        "## Acceptance Criteria\n"
        "~~~\n[NEEDS CLARIFICATION: tilde example]\n~~~\n\n"
        "    [NEEDS CLARIFICATION: indented example]\n"
    )
    assert sc.unresolved_markers(text) == []


def test_fenced_heading_does_not_hide_a_real_marker():
    # A `## …` line INSIDE a fenced example must not be treated as a section
    # boundary; a REAL marker in the actual Acceptance Criteria section must still
    # be seen and block. (Regression: strip code BEFORE deriving sections.)
    spec = (
        "## Goals\n"
        "Show the ordering hazard.\n\n"
        "```text\n"
        "## Acceptance Criteria\n"
        "this heading is only an example inside a fence\n"
        "```\n\n"
        "## Acceptance Criteria\n"
        "- [ ] AC-1: the gate · blocks · ack · when [NEEDS CLARIFICATION: real one] remains\n"
    )
    assert sc.unresolved_markers(spec), "real marker in the requirement section must be found"
    rep = sc.self_check(spec, "M")
    assert not rep.ok
    assert any(f.dimension == "markers" for f in rep.blocking)


def test_marker_in_narrative_prose_does_not_self_block():
    # A meta-spec that DOCUMENTS the marker in its narrative (Goals / Non-goals)
    # must not self-block — only markers in requirement sections block.
    text = (
        "## Goals\n"
        "Add a check that surfaces [NEEDS CLARIFICATION] markers in specs.\n\n"
        "## Non-goals\n"
        "Do not adjudicate a [NEEDS CLARIFICATION] item — that is the human's call.\n\n"
        "## Acceptance Criteria\n"
        "- [ ] AC-1: the check · surfaces · every open marker · when one remains in a requirement\n"
    )
    assert sc.unresolved_markers(text) == []
    assert sc.self_check(text, "M").ok


# --- testability (heuristic, SURFACE) ---------------------------------------

def test_untestable_ac_surfaced():
    spec = _GOOD_SPEC.replace(
        "· when a segment is missing", "· when it works correctly"
    )
    rep = sc.self_check(spec, "M")
    assert any(f.dimension == "testability" for f in rep.surfaced)
    assert rep.ok  # heuristic surfaces, never blocks


# --- WHAT-not-HOW (heuristic, SURFACE) --------------------------------------

def test_what_not_how_surfaced():
    spec = _GOOD_SPEC.replace(
        "Provide a deterministic gate that checks the acceptance criteria of a spec.",
        "Parse the config via the yaml.load call inside core/skills/foo.py.",
    )
    rep = sc.self_check(spec, "M")
    assert any(f.dimension == "what-not-how" for f in rep.surfaced)
    assert rep.ok


def test_what_not_how_exempts_file_ref_in_ac():
    # A structured AC that legitimately names a file (in its Object/Condition)
    # must NOT be flagged as WHAT-not-HOW (only the bare file-path cue is exempt).
    spec = _GOOD_SPEC.replace(
        "2. AC-2: the reader · surfaces · the constitution checklist · when the file is present",
        "2. AC-2: the reader · loads · config/constitution.yml · when the file is present",
    )
    rep = sc.self_check(spec, "M")
    assert not any(f.dimension == "what-not-how" for f in rep.surfaced)


# --- contradiction (heuristic, SURFACE) -------------------------------------

def test_contradiction_surfaced():
    spec = _GOOD_SPEC.replace(
        "2. AC-2: the reader · surfaces · the constitution checklist · when the file is present",
        "2. AC-2: the gate · accepts · a spec whose AC is not in SAOC form · when a segment is missing",
    )
    rep = sc.self_check(spec, "M")
    assert any(f.dimension == "contradiction" for f in rep.surfaced)


# --- completeness (heuristic, SURFACE) --------------------------------------

def test_uncovered_goal_surfaced():
    spec = _GOOD_SPEC.replace(
        "Provide a deterministic gate that checks the acceptance criteria of a spec.",
        "Guarantee idempotent migration rollback across concurrent writers.",
    )
    rep = sc.self_check(spec, "M")
    assert any(f.dimension == "completeness" for f in rep.surfaced)


# --- constitution surfacing (reuses the KLC-082 reader) ---------------------

def test_constitution_checklist_reuses_reader():
    rep = sc.self_check(_GOOD_SPEC, "M")
    # Every review principle must appear as a surfaced checklist item.
    review_ids = {p["id"] for p in con.review()}
    surfaced_ids = {f.ref for f in rep.surfaced if f.dimension == "constitution"}
    assert review_ids and review_ids <= surfaced_ids
    assert {p["id"] for p in rep.constitution_checklist} == review_ids


def test_constitution_degrades_when_absent(monkeypatch):
    # Force the reader to fail (file missing) — the gate must not crash and must
    # emit a single degraded note instead of the checklist.
    monkeypatch.setattr(con, "constitution_path", lambda: Path("/no/such/constitution.yml"))
    rep = sc.self_check(_GOOD_SPEC, "M")
    con_findings = [f for f in rep.findings if f.dimension == "constitution"]
    assert len(con_findings) == 1
    assert "unavailable" in con_findings[0].message
    assert rep.constitution_checklist == []
    # Other dimensions still ran; the gate still returned a verdict.
    assert rep.ok


def test_constitution_degrades_on_malformed_principle(monkeypatch):
    # A loadable-but-malformed principle (missing id/statement) must degrade to a
    # single note, not crash self_check (degrade-not-fail is itself a principle).
    monkeypatch.setattr(con, "review", lambda: [{"check": "review", "category": "x"}])
    rep = sc.self_check(_GOOD_SPEC, "M")
    con_findings = [f for f in rep.findings if f.dimension == "constitution"]
    assert len(con_findings) == 1
    assert "degraded" in con_findings[0].message
    assert rep.constitution_checklist == []
    assert rep.ok


# --- track scaling -----------------------------------------------------------

def test_xs_light_skips_heavy_dimensions():
    # A spec that would trip testability + what-not-how + contradiction, on XS.
    spec = _GOOD_SPEC.replace("· when a segment is missing", "· when it works correctly")
    rep = sc.self_check(spec, "XS")
    dims = _dims(rep)
    assert dims <= {"format", "markers", "constitution"}
    assert "testability" not in dims


def test_m_full_runs_heavy_dimensions():
    spec = _GOOD_SPEC.replace("· when a segment is missing", "· when it works correctly")
    rep = sc.self_check(spec, "M")
    assert "testability" in _dims(rep)


def test_xs_surfaces_format_but_does_not_block():
    spec = _GOOD_SPEC.replace(
        "1. AC-1: the gate · rejects · a spec whose AC is not in SAOC form · when a segment is missing",
        "1. AC-1: not saoc at all",
    )
    rep = sc.self_check(spec, "XS")
    assert rep.ok  # non-SAOC format surfaces, does not hard-fail even on XS
    assert any(f.dimension == "format" for f in rep.surfaced)


def test_xs_blocks_duplicate_id():
    # A duplicate id is an OBJECTIVE defect in the LIGHT set — XS must catch it.
    spec = _GOOD_SPEC.replace(
        "2. AC-2: the reader · surfaces · the constitution checklist · when the file is present",
        "2. AC-1: the reader · surfaces · the checklist · when the file is present",
    )
    rep = sc.self_check(spec, "XS")
    assert not rep.ok
    assert any(f.dimension == "format" and "duplicate" in f.message for f in rep.blocking)


def test_xs_direct_open_marker_blocks():
    # A direct XS spec with an open marker in the AC section must block.
    spec = _GOOD_SPEC.replace(
        "· when a segment is missing",
        "· when a segment is missing\n- [ ] AC-3: the author · resolves · the unknown "
        "· when [NEEDS CLARIFICATION: which floor?] is answered",
    )
    rep = sc.self_check(spec, "XS")
    assert not rep.ok
    assert any(f.dimension == "markers" for f in rep.blocking)


# --- (bool, str) gate adapter -----------------------------------------------

def test_gate_adapter_blocks_on_marker():
    spec = _GOOD_SPEC.replace("## Estimate", "[NEEDS CLARIFICATION: x]\n\n## Estimate")
    ok, msg = sc.gate(spec, "M")
    assert not ok and "self-check" in msg


def test_gate_adapter_passes_clean_spec():
    ok, _ = sc.gate(_GOOD_SPEC, "M")
    assert ok
