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


# === KLC-089 (E-05) — coverage dimension + vague-adjective blocklist =========

import elicitation as _elic  # noqa: E402  (the E-02 scan seam the coverage dim reads)


def _cov(cat_id, status):
    """A CategoryCoverage double, built through the real elicitation dataclass so
    the tests read the same status vocabulary the seam emits (single-source)."""
    return _elic.CategoryCoverage(id=cat_id, status=status)


# --- step-1: the coverage dimension (calls scan_coverage, SURFACE, degrade) ---

def test_coverage_calls_scan_coverage(monkeypatch):
    # AC-1 / AC-8: the dimension derives its findings ONLY from what
    # elicitation.scan_coverage returns — proving it reads the E-02 scan rather
    # than re-implementing the classifier or re-parsing the taxonomy.
    seen = {}

    def fake_scan(text, track):
        seen["args"] = (text, track)
        return [_cov("edge-failure", _elic.MISSING)]

    monkeypatch.setattr(_elic, "scan_coverage", fake_scan)
    findings = sc._check_coverage("some spec body", "S")
    assert seen["args"] == ("some spec body", "S")
    assert any(f.dimension == "coverage" and f.ref == "edge-failure"
               and "edge-failure" in f.message for f in findings)


def test_coverage_surfaces_missing_never_blocks(monkeypatch):
    # AC-2 / AC-3: every Missing mandatory category is SURFACEd, never BLOCKed.
    monkeypatch.setattr(
        _elic, "scan_coverage",
        lambda text, track: [_cov("nfr", _elic.MISSING),
                             _cov("edge-failure", _elic.MISSING)])
    findings = sc._check_coverage("body", "S")
    assert findings  # both Missing categories surfaced
    assert all(f.severity == sc.SURFACE for f in findings)
    assert not any(f.severity == sc.BLOCK for f in findings)
    assert {f.ref for f in findings} == {"nfr", "edge-failure"}


def test_coverage_degrades_when_elicitation_unavailable(monkeypatch):
    # AC-5: when the scan raises, the dimension yields exactly ONE degraded
    # SURFACE note and swallows the exception (so self_check's other dimensions,
    # dispatched independently, still run — never a crashed ack).
    def boom(text, track):
        raise RuntimeError("taxonomy gone")

    monkeypatch.setattr(_elic, "scan_coverage", boom)
    findings = sc._check_coverage("body", "M")
    assert len(findings) == 1
    note = findings[0]
    assert note.dimension == "coverage"
    assert note.severity == sc.SURFACE
    assert "degrad" in note.message.lower() or "unavailable" in note.message.lower()


def test_coverage_degrades_when_scan_returns_malformed(monkeypatch):
    # AC-5 (LOW-1 hardening): a MALFORMED scan return — not only a raise — must
    # also degrade to exactly one SURFACE note and never propagate out of
    # _check_coverage / self_check. Two shapes exercise the comprehension guard:
    # a non-iterable (None → TypeError) and an element lacking .status/.id
    # (AttributeError). Both must be caught INSIDE _check_coverage's try.
    class _Bad:  # an element with neither .status nor .id
        pass

    for bad_return in (None, [_Bad()]):
        monkeypatch.setattr(_elic, "scan_coverage", lambda text, track, _r=bad_return: _r)
        # direct: exactly one degraded SURFACE note, no exception
        findings = sc._check_coverage("body", "M")
        assert len(findings) == 1
        assert findings[0].dimension == "coverage"
        assert findings[0].severity == sc.SURFACE
        # end to end: self_check still completes, coverage never blocks, other
        # dimensions still run
        rep = sc.self_check(_GOOD_SPEC, "M")
        cov = [f for f in rep.findings if f.dimension == "coverage"]
        assert len(cov) == 1 and cov[0].severity == sc.SURFACE
        assert rep.ok
        assert any(f.dimension != "coverage" for f in rep.findings)


# --- step-2: vague-adjective blocklist folded into `testability` -------------

def _spec_with_ac(ac_line: str) -> str:
    """A minimal but well-formed spec carrying one SAOC acceptance criterion."""
    return (
        "## Goals\nProvide a gate.\n\n"
        "## Acceptance Criteria\n"
        f"1. {ac_line}\n\n"
        "## Estimate\ntotal: 4\n"
    )


def _vague_findings(rep):
    return [f for f in rep.surfaced
            if f.dimension == "testability" and "vague adjective" in f.message]


def test_vague_adjective_surfaced_whole_word():
    # AC-6: a blocklisted quality adjective used with no measurable criterion is
    # SURFACEd by the testability dimension.
    spec = _spec_with_ac(
        "AC-1: the system · is · secure · when it processes external requests")
    rep = sc.self_check(spec, "M")
    vague = _vague_findings(rep)
    assert any("secure" in f.message and f.ref == "AC-1" for f in vague)
    assert all(f.severity == sc.SURFACE for f in vague)


def test_vague_adjective_substring_not_flagged():
    # AC-7: whole-word matching — `secure` fires, but the substring inside
    # `security` (a different word) must NOT.
    spec = _spec_with_ac(
        "AC-1: the system · passes · a security review · when it is audited")
    rep = sc.self_check(spec, "M")
    assert _vague_findings(rep) == []


def test_vague_adjective_quantified_not_flagged():
    # A blocklisted adjective backed by a measurable criterion (a number in the
    # AC body) is a specified quality, not an asserted one → left quiet.
    spec = _spec_with_ac(
        "AC-1: the API · responds · fast (p95 under 200ms) · when it is queried")
    rep = sc.self_check(spec, "M")
    assert _vague_findings(rep) == []


# --- step-3: registry + track gating + ack integration ----------------------

def _cov_findings(rep):
    return [f for f in rep.findings if f.dimension == "coverage"]


def test_coverage_off_on_xs_active_on_s(monkeypatch):
    # AC-4: the coverage dimension is HEAVY — gated OFF on XS, active on S. Even
    # with a Missing category available, XS surfaces nothing from coverage.
    monkeypatch.setattr(
        _elic, "scan_coverage",
        lambda text, track: [_cov("edge-failure", _elic.MISSING)])
    xs = sc.self_check(_GOOD_SPEC, "XS")
    s = sc.self_check(_GOOD_SPEC, "S")
    assert _cov_findings(xs) == []
    assert any(f.ref == "edge-failure" for f in _cov_findings(s))
    assert all(f.severity == sc.SURFACE for f in _cov_findings(s))


def test_coverage_partial_surfaced_on_m_not_s(monkeypatch):
    # AC-4: a Partial category is left quiet on the light track (S) but surfaced
    # on M/L — the track-scaling is a real bound decided inside _check_coverage.
    monkeypatch.setattr(
        _elic, "scan_coverage",
        lambda text, track: [_cov("interaction-ux", _elic.PARTIAL)])
    s = sc.self_check(_GOOD_SPEC, "S")
    m = sc.self_check(_GOOD_SPEC, "M")
    assert _cov_findings(s) == []
    assert any(f.ref == "interaction-ux" for f in _cov_findings(m))


def test_coverage_degrade_keeps_other_dimensions(monkeypatch):
    # AC-5 end-to-end: when the scan raises, self_check yields exactly one degraded
    # coverage SURFACE note AND every other dimension still runs (never blocks).
    def boom(text, track):
        raise RuntimeError("taxonomy gone")

    monkeypatch.setattr(_elic, "scan_coverage", boom)
    rep = sc.self_check(_GOOD_SPEC, "M")
    cov = _cov_findings(rep)
    assert len(cov) == 1 and cov[0].severity == sc.SURFACE
    assert any(f.dimension != "coverage" for f in rep.findings)  # others ran
    assert rep.ok  # coverage never blocks, degraded or not


def test_coverage_finding_reaches_ack_warn_lines(monkeypatch):
    # AC-3 (end to end): a Missing coverage category reaches the ack path's warn
    # lines as an advisory and NEVER the block message — warn-only, end to end.
    import phase_completion as pc  # noqa: E402  (the real ack call site)

    monkeypatch.setattr(
        _elic, "scan_coverage",
        lambda text, track: [_cov("edge-failure", _elic.MISSING)])
    block_msg, warn_lines = pc._spec_quality_gate(_GOOD_SPEC, {"track": "S"})
    assert block_msg == ""  # coverage never blocks the ack
    assert any("coverage" in line and "edge-failure" in line for line in warn_lines)
