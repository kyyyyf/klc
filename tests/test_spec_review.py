#!/usr/bin/env python3
"""Tests for core/skills/spec_review.py — the independent spec-review plumbing
(KLC-084) — and a structural test of the reviewer prompt.

Covers: the two-output schema parse+validate, the recommended-answer rule,
routing decisions_to_confirm to the ack decision gate, findings recording,
track-scaling (M/L full · S cascade · XS skip) with signal escalation, the
degrade-when-inputs-absent paths, the consume() seam, and a structural check
of core/agents/spec-reviewer.md.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import spec_review as sr  # noqa: E402


# --- a well-formed reviewer verdict block -----------------------------------

_GOOD = {
    "findings": [
        {
            "id": "F-1",
            "category": "infidelity",
            "severity": "high",
            "ref": "AC-3",
            "detail": "spec drops a raw.md behaviour",
            "suggested_fix": "add the AC",
        },
        {
            "id": "F-2",
            "category": "code-contradiction",
            "severity": "medium",
            "ref": "AC-5",
            "detail": "names a verb that does not exist",
        },
    ],
    "decisions_to_confirm": [
        {
            "id": "D-1",
            "topic": "scope",
            "question": "flag style too?",
            "recommended": "no — only the five categories",
            "rationale": "keeps it low-noise",
        }
    ],
}


def _block(doc: dict) -> str:
    return "some narrative\n\n```json\n" + json.dumps(doc) + "\n```\n"


# --- parse + validate -------------------------------------------------------

def test_parse_good_block():
    out = sr.parse_review(_block(_GOOD))
    assert not out.degraded
    assert len(out.findings) == 2
    assert len(out.decisions_to_confirm) == 1
    assert out.findings[0].category == "infidelity"
    assert out.decisions_to_confirm[0].recommended.startswith("no")


def test_validate_clean():
    assert sr.validate(sr.parse_review(_block(_GOOD))) == []


def test_last_json_block_wins():
    # An earlier example block must not shadow the real verdict block.
    stale = _block({"findings": [{"id": "X"}], "decisions_to_confirm": []})
    text = stale + "\nmore\n" + _block(_GOOD)
    out = sr.parse_review(text)
    assert {f.id for f in out.findings} == {"F-1", "F-2"}


def test_unknown_category_flagged():
    doc = {"findings": [{"id": "F-1", "category": "bogus",
                         "severity": "high", "detail": "x"}],
           "decisions_to_confirm": []}
    errs = sr.validate(sr.parse_review(_block(doc)))
    assert any("unknown category" in e for e in errs)


def test_unknown_severity_flagged():
    doc = {"findings": [{"id": "F-1", "category": "infidelity",
                         "severity": "blocker", "detail": "x"}],
           "decisions_to_confirm": []}
    errs = sr.validate(sr.parse_review(_block(doc)))
    assert any("unknown severity" in e for e in errs)


def test_empty_detail_flagged():
    doc = {"findings": [{"id": "F-1", "category": "infidelity",
                         "severity": "high", "detail": "  "}],
           "decisions_to_confirm": []}
    errs = sr.validate(sr.parse_review(_block(doc)))
    assert any("empty detail" in e for e in errs)


def test_duplicate_id_flagged():
    doc = {"findings": [
        {"id": "F-1", "category": "infidelity", "severity": "high", "detail": "a"},
        {"id": "F-1", "category": "constitution", "severity": "low", "detail": "b"},
    ], "decisions_to_confirm": []}
    errs = sr.validate(sr.parse_review(_block(doc)))
    assert any("duplicate id" in e for e in errs)


# --- the recommended-answer rule (the core discipline) ----------------------

def test_missing_recommendation_is_a_schema_error():
    doc = {"findings": [], "decisions_to_confirm": [
        {"id": "D-1", "topic": "tradeoff", "question": "A or B?", "recommended": ""}
    ]}
    errs = sr.validate(sr.parse_review(_block(doc)))
    assert any("missing recommended" in e for e in errs)


def test_unknown_topic_flagged():
    doc = {"findings": [], "decisions_to_confirm": [
        {"id": "D-1", "topic": "vibes", "question": "?", "recommended": "yes"}
    ]}
    errs = sr.validate(sr.parse_review(_block(doc)))
    assert any("unknown topic" in e for e in errs)


def test_empty_question_flagged():
    doc = {"findings": [], "decisions_to_confirm": [
        {"id": "D-1", "topic": "scope", "question": "", "recommended": "yes"}
    ]}
    errs = sr.validate(sr.parse_review(_block(doc)))
    assert any("empty question" in e for e in errs)


# --- routing decisions_to_confirm to the ack decision gate ------------------

def test_route_decisions_leads_with_recommendation():
    lines = sr.route_decisions(sr.parse_review(_block(_GOOD)))
    assert len(lines) == 1
    assert "RECOMMENDED:" in lines[0]
    assert "D-1" in lines[0] and "scope" in lines[0]
    # The recommendation text is present (lead-with-a-recommendation).
    assert "only the five categories" in lines[0]


def test_route_decisions_empty_when_none():
    doc = {"findings": _GOOD["findings"], "decisions_to_confirm": []}
    assert sr.route_decisions(sr.parse_review(_block(doc))) == []


# --- findings recording -----------------------------------------------------

def test_record_findings_returns_dicts():
    recs = sr.record_findings(sr.parse_review(_block(_GOOD)))
    assert [r["id"] for r in recs] == ["F-1", "F-2"]
    assert recs[0]["category"] == "infidelity"


def test_record_findings_writes_file(tmp_path):
    sr.record_findings(sr.parse_review(_block(_GOOD)), tmp_path)
    path = tmp_path / "spec-review-findings.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert {d["id"] for d in data} == {"F-1", "F-2"}


# --- track scaling ----------------------------------------------------------

def test_review_mode_by_track():
    assert sr.review_mode("M") == "full"
    assert sr.review_mode("L") == "full"
    assert sr.review_mode("S") == "cascade"
    assert sr.review_mode("XS") == "skip"


def test_should_run_full_and_skip():
    assert sr.should_run("M") is True
    assert sr.should_run("L") is True
    assert sr.should_run("XS") is False


def test_should_run_cascade_needs_a_signal():
    # S with no signal -> no review; S with a risk tag -> review.
    assert sr.should_run("S") is False
    assert sr.should_run("S", {"risk_tags": ["security"]}) is True
    assert sr.should_run("S", {"scope_expansion": ["mod-x"]}) is True
    assert sr.should_run("S", {"sentinel_hits": 2}) is True
    assert sr.should_run("S", {"risk_tags": ["cosmetic"]}) is False


def test_unknown_track_defaults_to_full():
    assert sr.review_mode(None) == "full"
    assert sr.should_run("") is True


# --- degrade-not-fail -------------------------------------------------------

def test_parse_absent_input_degrades():
    for bad in (None, "", "   ", "no json here at all"):
        out = sr.parse_review(bad)
        assert out.degraded
        assert out.degrade_reason


def test_malformed_json_degrades_not_raises():
    out = sr.parse_review("```json\n{not valid json,}\n```")
    assert out.degraded


def test_validate_degraded_has_no_errors():
    assert sr.validate(sr.parse_review(None)) == []


def test_route_degraded_surfaces_one_note():
    lines = sr.route_decisions(sr.parse_review(None))
    assert len(lines) == 1
    assert "degraded" in lines[0]


# --- the consume() seam -----------------------------------------------------

def test_consume_absent_output_on_full_track_surfaces_note(tmp_path):
    advisories, findings = sr.consume(tmp_path, "M")
    assert findings == []
    assert len(advisories) == 1
    assert "expected" in advisories[0] and "degraded" in advisories[0]


def test_consume_absent_output_on_skip_track_is_silent(tmp_path):
    advisories, findings = sr.consume(tmp_path, "XS")
    assert advisories == [] and findings == []


def test_consume_absent_output_on_cascade_no_signal_is_silent(tmp_path):
    advisories, findings = sr.consume(tmp_path, "S")
    assert advisories == [] and findings == []


def test_consume_reads_output_routes_and_records(tmp_path):
    (tmp_path / "spec-review.md").write_text(_block(_GOOD), encoding="utf-8")
    advisories, findings = sr.consume(tmp_path, "M")
    assert any("RECOMMENDED:" in a for a in advisories)
    assert {f["id"] for f in findings} == {"F-1", "F-2"}
    assert (tmp_path / "spec-review-findings.json").exists()


def test_consume_surfaces_schema_errors(tmp_path):
    bad = {"findings": [{"id": "F-1", "category": "bogus",
                         "severity": "high", "detail": "x"}],
           "decisions_to_confirm": []}
    (tmp_path / "spec-review.md").write_text(_block(bad), encoding="utf-8")
    advisories, _ = sr.consume(tmp_path, "M")
    assert any("schema" in a for a in advisories)


# A KLC-085-shaped kind with a GENUINELY DIFFERENT category set + topic set. If
# the seam were still module-global, validate() would reject these categories.
_TEST_PLAN_KIND = sr.ReviewKind(
    name="test-plan",
    reviewer_prompt="core/agents/test-plan-reviewer.md",
    artifact="test-plan.md",
    output_file="test-plan-review.md",
    finding_categories=("uncovered-ac", "weak-assertion", "missing-edge-case"),
    decision_topics=("coverage-depth", "fixture-strategy"),
)

_TP_VERDICT = {
    "findings": [
        {"id": "T-1", "category": "uncovered-ac", "severity": "high",
         "ref": "AC-2", "detail": "no test drives AC-2"},
        {"id": "T-2", "category": "weak-assertion", "severity": "low",
         "ref": "AC-4", "detail": "asserts truthiness, not the value"},
    ],
    "decisions_to_confirm": [
        {"id": "C-1", "topic": "coverage-depth",
         "question": "property-test the parser or example-test it?",
         "recommended": "example tests — the input space is small"}
    ],
}


def test_seam_accepts_a_different_category_set_and_uses_kind_label():
    # NON-tautological: these categories are NOT in SPEC_REVIEW's set, yet
    # validate() (reading FROM the kind) accepts them, and the label uses the
    # kind's name — proving KLC-085 can reuse the module with its own vocab.
    out = sr.parse_review(_block(_TP_VERDICT))
    assert sr.validate(out, _TEST_PLAN_KIND) == []
    # The SAME verdict is rejected under SPEC_REVIEW's categories (control).
    assert sr.validate(out, sr.SPEC_REVIEW) != []
    lines = sr.route_decisions(out, _TEST_PLAN_KIND)
    assert lines and lines[0].startswith("test-plan-review[decision C-1/coverage-depth]")


def test_consume_generic_seam_for_other_kinds(tmp_path):
    (tmp_path / "test-plan-review.md").write_text(_block(_TP_VERDICT), encoding="utf-8")
    advisories, findings = sr.consume(tmp_path, "M", kind=_TEST_PLAN_KIND)
    assert any("RECOMMENDED:" in a for a in advisories)
    assert any(a.startswith("test-plan-review[decision") for a in advisories)
    # its own categories validated clean (no schema advisory).
    assert not any("schema" in a for a in advisories)
    assert (tmp_path / "test-plan-review-findings.json").exists()


# --- MEDIUM-2: a wrong-shape JSON block must degrade, not read as clean --------

def test_wrong_shape_block_degrades():
    # An orchestrator completion signal has neither output key.
    signal = '```json\n{"phase":"spec-review","signal":"done","artifacts":[]}\n```'
    out = sr.parse_review(signal)
    assert out.degraded
    assert "neither findings nor decisions_to_confirm" in out.degrade_reason


def test_wrong_shape_does_not_read_as_issue_free(tmp_path):
    signal = '```json\n{"phase":"spec-review","signal":"done"}\n```'
    (tmp_path / "spec-review.md").write_text(signal, encoding="utf-8")
    advisories, _ = sr.consume(tmp_path, "M")
    # Must surface the degrade, not silently pass as a clean spec.
    assert any("degraded" in a for a in advisories)


def test_only_decisions_key_is_a_valid_verdict():
    # Having just ONE of the two keys is still a real verdict (not degraded).
    doc = {"decisions_to_confirm": [
        {"id": "D-1", "topic": "scope", "question": "?", "recommended": "no"}]}
    out = sr.parse_review(_block(doc))
    assert not out.degraded
    assert len(out.decisions_to_confirm) == 1


# --- HIGH-1(a): the OBJECTIVE findings are surfaced at the ack ----------------

def test_summarize_findings_counts_and_flags_high():
    lines = sr.summarize_findings(sr.parse_review(_block(_GOOD)))
    assert len(lines) == 1
    assert "2 finding(s) recorded" in lines[0]
    assert "1 high" in lines[0]
    assert "assess before build" in lines[0]


def test_summarize_findings_empty_when_none():
    doc = {"findings": [], "decisions_to_confirm": _GOOD["decisions_to_confirm"]}
    assert sr.summarize_findings(sr.parse_review(_block(doc))) == []


def test_consume_surfaces_findings_summary(tmp_path):
    (tmp_path / "spec-review.md").write_text(_block(_GOOD), encoding="utf-8")
    advisories, _ = sr.consume(tmp_path, "M")
    assert any("finding(s) recorded" in a for a in advisories)


# --- codex P2: a read-only probe must not write ------------------------------

def test_consume_probe_does_not_write(tmp_path):
    (tmp_path / "spec-review.md").write_text(_block(_GOOD), encoding="utf-8")
    advisories, findings = sr.consume(tmp_path, "M", persist=False)
    # Still surfaces (routes + summary) ...
    assert any("RECOMMENDED:" in a for a in advisories)
    assert any("finding(s) recorded" in a for a in advisories)
    # ... but writes nothing on the read-only path.
    assert not (tmp_path / "spec-review-findings.json").exists()


def test_consume_persist_true_writes(tmp_path):
    (tmp_path / "spec-review.md").write_text(_block(_GOOD), encoding="utf-8")
    sr.consume(tmp_path, "M", persist=True)
    assert (tmp_path / "spec-review-findings.json").exists()


# --- structural test of the reviewer PROMPT ---------------------------------

def test_reviewer_prompt_exists_and_covers_the_contract():
    txt = (_FW_ROOT / "core/agents/spec-reviewer.md").read_text(encoding="utf-8")
    low = txt.lower()
    # raw.md fidelity anchor.
    assert "raw.md" in txt and ("fidelity" in low or "infidelity" in low)
    # constitution checklist via the KLC-082 reader (single source).
    assert "constitution" in low and "constitution.py" in txt
    # KLC-083 self-check surfaced findings.
    assert "spec_selfcheck" in txt
    # both output classes.
    assert "findings[]" in txt and "decisions_to_confirm[]" in txt
    # the recommended-answer rule.
    assert "recommend" in low
    # never adjudicates the subjective class.
    assert "elevate" in low or "never adjudicate" in low


def test_reviewer_prompt_schema_matches_the_plumbing_vocab():
    # No contradiction between the prompt's stated vocab and the schema constants.
    txt = (_FW_ROOT / "core/agents/spec-reviewer.md").read_text(encoding="utf-8")
    for cat in sr.FINDING_CATEGORIES:
        assert cat in txt, f"prompt is missing finding category {cat!r}"
    for topic in sr.DECISION_TOPICS:
        assert topic in txt, f"prompt is missing decision topic {topic!r}"


def test_reviewer_prompt_has_no_prejudgment_language():
    # Reuse the existing no-pre-judgment lint so the reviewer stays unbiased.
    import lint_review_prompts as lint
    txt = (_FW_ROOT / "core/agents/spec-reviewer.md").read_text(encoding="utf-8")
    assert lint.lint_text(txt) == []


def test_reviewer_prompt_instructs_both_sinks():
    """The prompt must instruct BOTH sinks so neither breaks:
      - the VERDICT is the last block of the FILE spec-review.md (so parse_review's
        last-block-wins grabs the verdict, not a signal), AND
      - the run_signal COMPLETION SIGNAL is the last block of the CHAT reply (so
        run_signal.parse_signal classifies a successful review as done, not a
        failed/unparseable run).
    Regression guard for the MEDIUM-2 over-correction that dropped the chat signal.
    """
    import run_signal
    txt = (_FW_ROOT / "core/agents/spec-reviewer.md").read_text(encoding="utf-8")
    low = txt.lower()

    # File sink: verdict is spec-review.md's last block.
    assert "spec-review.md" in txt
    assert "last block" in low and "verdict" in low

    # Chat sink: the run_signal completion signal is present with every required key.
    assert "run_signal" in txt or "completion signal" in low
    for key in run_signal.REQUIRED_KEYS:
        assert f'"{key}"' in txt, f"completion signal missing required key {key!r}"

    # And the prompt's actual signal example must PARSE through run_signal — this
    # is what a dispatched reviewer's chat reply ends with; if it doesn't parse,
    # a successful review is misclassified as a failed run (the MEDIUM-2 breakage).
    signal_block = re.search(r'\{"phase":\s*"spec-review".*?\}', txt, re.DOTALL)
    assert signal_block, "no spec-review completion-signal example in the prompt"
    parsed = run_signal.parse_signal(f"```json\n{signal_block.group(0)}\n```",
                                     "spec-review")
    assert parsed is not None and parsed.signal == "done"

    # The two are explicitly separated (chat vs file), not merged.
    assert "chat" in low and ("file" in low)
