#!/usr/bin/env python3
"""Tests for core/skills/testplan_review.py — the KLC-085 adversarial-coverage
review of a test-plan against the spec's SAOC ACs.

Covers: the AC→test coverage map (uncovered AC flagged; fully-covered plan clean),
happy-path-only detection, the gate/reject-AC-without-a-negative-test heuristic,
track scaling (XS skip / S light / M full), degrade-not-fail (absent ACs, absent
test-plan), the guard-and-reuse seam path (present vs absent), and a structural
test on the reviewer PROMPT.
"""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import testplan_review as tr  # noqa: E402
import spec_review as sr  # noqa: E402


_SPEC = """\
---
ticket: KLC-XXX
kind: feature
track: M
---

## Goals
Provide an adversarial coverage review of a test-plan.

## Acceptance Criteria
1. AC-1: the review · maps · each AC to a planned test · when it reviews a test-plan
2. AC-2: the gate · rejects · a spec AC with no test · when the coverage table omits it
"""

# A plan that covers both ACs, with a real negative/edge case for the gate AC-2.
_PLAN_FULL = """\
---
ticket: KLC-XXX
authority: hybrid
---

# Test plan — KLC-XXX

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_map.py::test_maps_each_ac | — |
| AC-2 | acceptance | tests/test_gate.py::test_rejects_uncovered_ac | negative: missing test |

## Edge cases
- an uncovered AC is flagged as a finding
- an empty test-plan degrades rather than crashing
"""

# A plan that lists AC-2 with only a placeholder location → uncovered.
_PLAN_UNCOVERED = """\
---
ticket: KLC-XXX
---

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_map.py::test_maps_each_ac | — |
| AC-2 | acceptance | — | TBD |

## Edge cases
- an uncovered AC is flagged
"""

# A happy-path-only plan: both ACs covered but no edge/negative signal at all.
_PLAN_HAPPY = """\
---
ticket: KLC-XXX
---

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_map.py::test_success | — |
| AC-2 | acceptance | tests/test_gate.py::test_success | — |

## Edge cases
-
"""


# A plan where AC-2 is genuinely uncovered, but AC-1's row Notes MENTION AC-2 in
# free text ("does not cover AC-2"). A Notes mention must NOT attribute coverage —
# AC ids count only from the dedicated AC column (regression for the FIX-2 bug).
_PLAN_NOTES_MENTIONS_OTHER_AC = """\
---
ticket: KLC-XXX
---

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_map.py::test_maps | does not cover AC-2 |
| AC-2 | acceptance | — | TBD |

## Edge cases
- an uncovered AC is flagged
"""

# A happy-path-only plan with an EMPTY ## Edge cases section AND a row that MENTIONS
# a negative case in its Notes but whose TEST LOCATION is a placeholder (no real
# test). The placeholder row must NOT count as negative-evidence, so happy_path must
# still fire (regression for the FIX-3 follow-on gap).
_PLAN_HAPPY_PLACEHOLDER_NEGATIVE = """\
---
ticket: KLC-XXX
---

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_map.py::test_success | maps each criterion |
| AC-2 | acceptance | — | negative: rejects invalid input (TBD) |

## Edge cases
-
"""

# A happy-path-only plan whose ## Edge cases section is FILLED with real bullets
# that carry NO negative/boundary token, and whose coverage rows carry none either.
# This must STILL be flagged happy_path — it exercises FIX-3's real detection, not
# the "edge section empty/placeholder" branch the older test relied on.
_PLAN_HAPPY_FILLED_EDGES = """\
---
ticket: KLC-XXX
---

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_map.py::test_success | maps every criterion |
| AC-2 | acceptance | tests/test_gate.py::test_success | happy path only |

## Edge cases
- the review maps each criterion to its planned test
- a fully covered plan reads as clean
"""


def _dims(rep):
    return {f.dimension for f in rep.surfaced}


# --- AC → test coverage map (AC-1, AC-2, AC-3) ------------------------------

def test_coverage_map_maps_each_ac():
    mapping = tr.coverage_map(_SPEC, _PLAN_FULL)
    assert set(mapping) == {"AC-1", "AC-2"}
    assert mapping["AC-1"] and mapping["AC-2"]


def test_uncovered_ac_is_flagged():
    rep = tr.review(_SPEC, _PLAN_UNCOVERED, "M")
    cov = [f for f in rep.surfaced if f.dimension == "coverage"]
    assert any(f.ref == "AC-2" for f in cov), rep.surfaced
    assert rep.coverage_map["AC-2"] == []  # placeholder location ≠ coverage


def test_fully_covered_plan_is_clean():
    rep = tr.review(_SPEC, _PLAN_FULL, "M")
    assert rep.ok, [f.message for f in rep.surfaced]
    assert not rep.surfaced


def test_notes_mention_of_other_ac_does_not_count_as_coverage():
    # FIX-2: a Notes column that merely names AC-2 must not attribute a test to it.
    mapping = tr.coverage_map(_SPEC, _PLAN_NOTES_MENTIONS_OTHER_AC)
    assert mapping["AC-2"] == [], mapping           # Notes mention ≠ coverage
    assert mapping["AC-1"], mapping                 # AC-1 is genuinely covered
    rep = tr.review(_SPEC, _PLAN_NOTES_MENTIONS_OTHER_AC, "M")
    cov = [f for f in rep.surfaced if f.dimension == "coverage"]
    assert any(f.ref == "AC-2" for f in cov), rep.surfaced  # AC-2 still uncovered


# --- happy-path-only detection (AC-4) ---------------------------------------

def test_happy_path_only_detected():
    rep = tr.review(_SPEC, _PLAN_HAPPY, "M")
    assert any(f.dimension == "happy_path" for f in rep.surfaced), rep.surfaced


def test_happy_path_only_detected_with_filled_but_happy_edges():
    # FIX-3/FIX-4: a plan with FILLED-but-all-happy edge bullets and no negative
    # coverage row must still be flagged happy_path. This FAILS before FIX-3
    # (the plan-wide "edge" token in the mandated `## Edge cases` heading used to
    # mask it).
    rep = tr.review(_SPEC, _PLAN_HAPPY_FILLED_EDGES, "M")
    assert any(f.dimension == "happy_path" for f in rep.surfaced), rep.surfaced


def test_happy_path_placeholder_negative_row_does_not_suppress():
    # FIX-3 follow-on: a row that mentions a negative case but has a PLACEHOLDER
    # test location is not real negative-evidence, so it must not suppress the
    # happy_path advisory when the Edge-cases section is also empty.
    rep = tr.review(_SPEC, _PLAN_HAPPY_PLACEHOLDER_NEGATIVE, "M")
    assert any(f.dimension == "happy_path" for f in rep.surfaced), rep.surfaced


def test_gate_ac_without_negative_test_flagged():
    # AC-2's Action is "rejects" (a gate) but its only row is happy-path.
    rep = tr.review(_SPEC, _PLAN_HAPPY, "M")
    nb = [f for f in rep.surfaced if f.dimension == "negative_boundary"]
    assert any(f.ref == "AC-2" for f in nb), rep.surfaced


# --- track scaling (AC-7) ---------------------------------------------------

def test_track_xs_skips_entirely():
    rep = tr.review(_SPEC, _PLAN_HAPPY, "XS")
    assert rep.surfaced == []
    assert tr._active_dimensions("XS") == set()


def test_track_s_runs_coverage_only():
    assert tr._active_dimensions("S") == {"coverage"}
    # A happy-path plan on S surfaces the uncovered/coverage dim only, not happy_path.
    rep = tr.review(_SPEC, _PLAN_HAPPY, "S")
    assert _dims(rep) <= {"coverage"}


def test_track_m_runs_full_set():
    assert tr._active_dimensions("M") == {"coverage", "happy_path", "negative_boundary"}


# --- degrade-not-fail (AC-8) ------------------------------------------------

def test_absent_acs_degrades():
    rep = tr.review("## Goals\nno acs here\n", _PLAN_FULL, "M")
    assert rep.degraded
    assert rep.surfaced  # a single degraded note, not a crash


def test_absent_test_plan_degrades():
    rep = tr.review(_SPEC, "", "M")
    assert rep.degraded
    assert rep.surfaced


# --- the REAL KLC-084 seam carries 085's vocabulary (no fork) ---------------

def test_testplan_review_kind_is_a_spec_review_kind():
    # TEST_PLAN_REVIEW is a spec_review.ReviewKind — the SAME generic descriptor
    # SPEC_REVIEW is, differing only in prompt/artifact/output/vocabulary.
    assert isinstance(tr.TEST_PLAN_REVIEW, sr.ReviewKind)
    k = tr.TEST_PLAN_REVIEW
    assert k.name == "test-plan"
    assert k.reviewer_prompt == "core/agents/test-plan-reviewer.md"
    assert k.artifact == "test-plan.md"
    assert k.output_file == "test-plan-review.md"
    assert set(k.finding_categories) == {"uncovered-ac", "weak-assertion", "missing-edge-case"}
    assert set(k.decision_topics) == {"coverage-depth", "risk-prioritization"}


def test_seam_accepts_testplan_vocabulary_and_rejects_spec_only():
    # NON-TAUTOLOGICAL proof the schema-generic seam genuinely carries 085's
    # vocabulary: a verdict using a TEST-PLAN category + topic validates CLEAN
    # under TEST_PLAN_REVIEW, but the SAME verdict is REJECTED under SPEC_REVIEW,
    # and a spec-only category is rejected under TEST_PLAN_REVIEW. One validator,
    # two vocabularies — proving the vocabulary lives on the kind, not the module.
    tp_verdict = sr.ReviewOutput(
        findings=[sr.Finding(id="F-1", category="uncovered-ac", severity="high",
                             detail="AC-3 maps to no planned test")],
        decisions_to_confirm=[sr.DecisionToConfirm(
            id="D-1", topic="coverage-depth",
            question="is one acceptance test enough for AC-2?",
            recommended="add a boundary case too")],
    )
    # Accepted under the test-plan kind.
    assert sr.validate(tp_verdict, tr.TEST_PLAN_REVIEW) == []
    # The SAME verdict is rejected under the spec kind (wrong category AND topic).
    spec_errs = sr.validate(tp_verdict, sr.SPEC_REVIEW)
    assert any("uncovered-ac" in e for e in spec_errs)
    assert any("coverage-depth" in e for e in spec_errs)

    # And a spec-only category is rejected under the test-plan kind (vice-versa).
    spec_verdict = sr.ReviewOutput(
        findings=[sr.Finding(id="F-1", category="infidelity", severity="low",
                             detail="drifts from raw.md")],
    )
    assert sr.validate(spec_verdict, sr.SPEC_REVIEW) == []
    tp_errs = sr.validate(spec_verdict, tr.TEST_PLAN_REVIEW)
    assert any("infidelity" in e for e in tp_errs)


def test_consume_reuses_seam_and_records_findings(tmp_path):
    # tr.consume delegates to the 084 seam bound to TEST_PLAN_REVIEW: it reads
    # test-plan-review.md, records findings, and returns advisories with the
    # test-plan label — no forked parser.
    (tmp_path / "test-plan-review.md").write_text(
        "narrative\n\n```json\n"
        '{"findings":[{"id":"F-1","category":"missing-edge-case","severity":"high",'
        '"detail":"AC-2 has no negative case"}],'
        '"decisions_to_confirm":[{"id":"D-1","topic":"risk-prioritization",'
        '"question":"prove the data-loss path first?","recommended":"yes"}]}\n```\n',
        encoding="utf-8",
    )
    advisories, findings = tr.consume(tmp_path, "M", {"risk_tags": []}, persist=True)
    assert len(findings) == 1 and findings[0]["category"] == "missing-edge-case"
    assert (tmp_path / "test-plan-review-findings.json").exists()  # persisted
    assert any(a.startswith("test-plan-review[decision") for a in advisories)
    assert any("finding(s) recorded" in a for a in advisories)


def test_consume_probe_does_not_write(tmp_path):
    # persist=False (read-only probe) surfaces advisories but writes NOTHING.
    (tmp_path / "test-plan-review.md").write_text(
        '```json\n{"findings":[{"id":"F-1","category":"uncovered-ac",'
        '"severity":"low","detail":"AC-1 uncovered"}],"decisions_to_confirm":[]}\n```\n',
        encoding="utf-8",
    )
    advisories, findings = tr.consume(tmp_path, "M", {"risk_tags": []}, persist=False)
    assert findings and not (tmp_path / "test-plan-review-findings.json").exists()
    assert advisories  # still surfaced


# --- structural test on the reviewer PROMPT (prose) -------------------------

def test_reviewer_prompt_structure():
    prompt = (_FW_ROOT / "core" / "agents" / "test-plan-reviewer.md").read_text(encoding="utf-8")
    low = prompt.lower()
    # Anchored on the spec's SAOC ACs.
    assert "saoc" in low and "spec_saoc" in low
    assert "acceptance criteri" in low or "ac-n" in low
    # The adversarial coverage dimensions.
    assert "coverage" in low
    assert "happy-path" in low or "happy path" in low
    assert "tautolog" in low
    assert "boundary" in low or "negative" in low
    # Scope is coverage DESIGN, not implementation / faked-in-code.
    assert "coverage design" in low
    assert "code reviewer" in low  # the not-faked-in-code job stays theirs
    # Reuses the REAL 084 seam, does not rebuild the plumbing.
    assert "klc-084" in low
    # The seam's OBJECTIVE finding categories and SUBJECTIVE decision topics.
    for cat in ("uncovered-ac", "weak-assertion", "missing-edge-case"):
        assert cat in low, cat
    for topic in ("coverage-depth", "risk-prioritization"):
        assert topic in low, topic


def test_reviewer_prompt_separates_the_two_sinks():
    # Structural: the reviewer prompt MUST keep the two sinks apart exactly as
    # 084's spec-reviewer.md does — the FILE test-plan-review.md's last block is
    # the VERDICT (findings + decisions, no completion signal), and the CHAT
    # reply's last block is the run_signal completion JSON.
    prompt = (_FW_ROOT / "core" / "agents" / "test-plan-reviewer.md").read_text(encoding="utf-8")
    low = prompt.lower()
    assert "test-plan-review.md" in low          # the verdict FILE
    assert "decisions_to_confirm" in low         # verdict carries decisions
    assert "run_signal" in low or "parse_signal" in low  # chat signal is parseable
    assert "completion signal" in low
    # The two sinks are explicitly named as distinct destinations.
    assert "chat" in low and "file" in low
    # A structurally valid completion signal that run_signal.parse_signal accepts
    # must be documented in the prompt.
    import run_signal as rs  # noqa: E402
    import re as _re
    blocks = _re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", prompt)
    parsed = [rs.parse_signal("```json\n" + b + "\n```", "acceptance-test-plan")
              for b in blocks]
    assert any(s is not None and s.next_action == "ack" for s in parsed), \
        "prompt must document a parseable acceptance-test-plan completion signal"
