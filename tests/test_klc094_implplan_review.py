#!/usr/bin/env python3
"""Tests for KLC-094 (V-01 · independent impl-plan review) — the THIRD instance of
the merged KLC-084 `ReviewKind` seam, after SPEC_REVIEW (KLC-084) and
TEST_PLAN_REVIEW (KLC-085).

E-094 adds ONLY a descriptor (`implplan_review.IMPL_PLAN_REVIEW`), a thin `consume`
wrapper delegating to `spec_review.consume`, an adversarial reviewer prompt
(`core/agents/impl-plan-reviewer.md`), a one-block extension of the KLC-093
build-start assessment step in `core/agents/impl.md` (now THREE findings files), a
`consume` wire at the ack that finalizes `impl-plan.md`, and a `docs/process.md`
correction — no forked parser, validator, router, or gate.

The seam test is deliberately NON-tautological: it drives the REAL
`spec_review.validate` under the new descriptor (accepts the five impl-plan
categories, REJECTS a spec-only category), so it cannot pass against a stub.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import spec_review as sr  # noqa: E402
import implplan_review as ipr  # noqa: E402

_AGENTS = _FW_ROOT / "core" / "agents"
_SKILLS = _FW_ROOT / "core" / "skills"
_IMPL = _AGENTS / "impl.md"
_REVIEWER = _AGENTS / "impl-plan-reviewer.md"
_DESIGN = _AGENTS / "design.md"
_DISCOVERY_LITE = _AGENTS / "discovery-lite.md"
_PROCESS = _FW_ROOT / "docs" / "process.md"

# The five OBJECTIVE finding categories and two SUBJECTIVE decision topics that the
# impl-plan flavour of the seam carries — the single source these tests anchor on.
_IMPLPLAN_CATEGORIES = (
    "missing-step", "wrong-sequencing", "untestable-step",
    "unaddressed-ac", "infeasible-red-green",
)
_IMPLPLAN_TOPICS = ("sequencing-tradeoff", "scope")

# The reviewer findings file the whole loop hangs on.
_IMPLPLAN_FINDINGS_FILE = "impl-plan-review-findings.json"
_TESTPLAN_FINDINGS_FILE = "test-plan-review-findings.json"
_SPEC_FINDINGS_FILE = "spec-review-findings.json"


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


# ===========================================================================
# step-1 — IMPL_PLAN_REVIEW descriptor + implplan_review.py thin binding
# ===========================================================================

def test_descriptor_carries_five_categories_two_topics():
    """AC-1: IMPL_PLAN_REVIEW is a spec_review.ReviewKind carrying the five
    impl-plan finding categories and the two decision topics — the SAME generic
    descriptor SPEC_REVIEW/TEST_PLAN_REVIEW are, differing only in prompt /
    artifact / output / vocabulary."""
    assert isinstance(ipr.IMPL_PLAN_REVIEW, sr.ReviewKind)
    k = ipr.IMPL_PLAN_REVIEW
    assert k.name == "impl-plan"
    assert k.reviewer_prompt == "core/agents/impl-plan-reviewer.md"
    assert k.artifact == "impl-plan.md"
    assert k.output_file == "impl-plan-review.md"
    assert set(k.finding_categories) == set(_IMPLPLAN_CATEGORIES)
    assert set(k.decision_topics) == set(_IMPLPLAN_TOPICS)


def test_validate_accepts_implplan_categories():
    """AC-1 (non-tautological, part 1): the REAL `spec_review.validate` accepts a
    verdict whose findings use ALL FIVE impl-plan categories and whose decisions
    use BOTH topics under `kind=IMPL_PLAN_REVIEW` — proving the vocabulary lives on
    the kind, not the module."""
    verdict = sr.ReviewOutput(
        findings=[
            sr.Finding(id=f"F-{i}", category=cat, severity="medium",
                       detail=f"{cat} finding detail")
            for i, cat in enumerate(_IMPLPLAN_CATEGORIES, start=1)
        ],
        decisions_to_confirm=[
            sr.DecisionToConfirm(
                id="D-1", topic="sequencing-tradeoff",
                question="build the parser before or after the router?",
                recommended="parser first — the router depends on its output"),
            sr.DecisionToConfirm(
                id="D-2", topic="scope",
                question="is the CLI flag in scope for this plan?",
                recommended="out — no AC names it"),
        ],
    )
    assert sr.validate(verdict, ipr.IMPL_PLAN_REVIEW) == []


def test_validate_rejects_spec_only_category_under_implplan_kind():
    """AC-1 (non-tautological, part 2): a spec-only category (`infidelity`) is
    REJECTED under IMPL_PLAN_REVIEW with an "unknown category" error, and — the
    vice-versa arm — an impl-plan-only category (`missing-step`) is rejected under
    SPEC_REVIEW. One validator, two vocabularies."""
    spec_verdict = sr.ReviewOutput(
        findings=[sr.Finding(id="F-1", category="infidelity", severity="low",
                             detail="spec drifts from raw.md")],
    )
    # Clean under the spec kind, rejected under the impl-plan kind.
    assert sr.validate(spec_verdict, sr.SPEC_REVIEW) == []
    ip_errs = sr.validate(spec_verdict, ipr.IMPL_PLAN_REVIEW)
    assert any("infidelity" in e and "category" in e for e in ip_errs), ip_errs

    # Vice-versa: an impl-plan-only category is rejected under the spec kind.
    ip_verdict = sr.ReviewOutput(
        findings=[sr.Finding(id="F-1", category="missing-step", severity="high",
                             detail="AC-3 has no step that builds it")],
    )
    assert sr.validate(ip_verdict, ipr.IMPL_PLAN_REVIEW) == []
    spec_errs = sr.validate(ip_verdict, sr.SPEC_REVIEW)
    assert any("missing-step" in e for e in spec_errs), spec_errs


def test_consume_delegates_to_spec_review_seam(tmp_path):
    """AC-2: implplan_review.consume delegates straight to spec_review.consume bound
    to IMPL_PLAN_REVIEW — it reads impl-plan-review.md, records findings to
    impl-plan-review-findings.json, and returns advisories with the impl-plan label.
    No forked parser."""
    (tmp_path / "impl-plan-review.md").write_text(
        "narrative preamble\n\n```json\n"
        '{"findings":[{"id":"F-1","category":"wrong-sequencing","severity":"high",'
        '"detail":"step-2 depends on step-3 output"}],'
        '"decisions_to_confirm":[{"id":"D-1","topic":"scope",'
        '"question":"is the migration in scope?","recommended":"no"}]}\n```\n',
        encoding="utf-8",
    )
    advisories, findings = ipr.consume(tmp_path, "M", {"risk_tags": []}, persist=True)
    assert len(findings) == 1 and findings[0]["category"] == "wrong-sequencing"
    assert (tmp_path / _IMPLPLAN_FINDINGS_FILE).exists()  # persisted
    assert any(a.startswith("impl-plan-review[decision") for a in advisories), advisories
    assert any("finding(s) recorded" in a for a in advisories), advisories


# ===========================================================================
# step-2 — impl-plan-reviewer.md adversarial prompt (two sinks + closed world)
# ===========================================================================

def _enum_after(text: str, label: str) -> set[str]:
    """Parse the explicit `<label>` ∈ `a | b | c` enumeration line in the prompt's
    Field rules into a token set. Used by the closed-world honesty check: it reads
    the prompt's OWN declared vocabulary, not a hand-listed guess."""
    m = re.search(rf"`{re.escape(label)}`\s*∈\s*`([^`]+)`", text)
    if not m:
        return set()
    return {tok.strip() for tok in m.group(1).split("|") if tok.strip()}


def test_prompt_names_all_five_categories():
    """AC-3: the reviewer prompt names all FIVE OBJECTIVE finding categories."""
    low = _read(_REVIEWER).lower()
    for cat in _IMPLPLAN_CATEGORIES:
        assert cat in low, f"prompt must name the finding category '{cat}'"


def test_prompt_names_both_decision_topics():
    """AC-3: the reviewer prompt names both SUBJECTIVE decision topics."""
    low = _read(_REVIEWER).lower()
    for topic in _IMPLPLAN_TOPICS:
        assert topic in low, f"prompt must name the decision topic '{topic}'"


def test_prompt_anchors_on_acs_and_spec_review_findings():
    """AC-3: the prompt states BOTH anchors — the spec's SAOC ACs (parsed via
    spec_saoc, not eyeballed) AND the recorded spec-review findings (a step must
    address every AC AND every recorded spec-review finding)."""
    text = _read(_REVIEWER)
    low = text.lower()
    # Anchor 1: the spec's SAOC acceptance criteria, parsed with spec_saoc.
    assert "saoc" in low and "spec_saoc" in low, "must anchor on the spec's SAOC ACs"
    assert "spec.md" in low
    # Anchor 2: the recorded spec-review findings.
    assert _SPEC_FINDINGS_FILE in text, (
        "must name spec-review-findings.json as the second anchor"
    )


def test_prompt_two_sinks_verdict_in_file_signal_in_chat():
    """AC-4: the prompt separates the FILE verdict from the CHAT completion signal
    into two distinct sinks — impl-plan-review.md's last block is the VERDICT
    (findings + decisions), the chat reply's last block is the run_signal
    completion JSON. Mirrors the spec-reviewer / test-plan-reviewer contract."""
    import run_signal as rs  # noqa: E402
    text = _read(_REVIEWER)
    low = text.lower()
    assert "impl-plan-review.md" in low            # the verdict FILE
    assert "decisions_to_confirm" in low           # verdict carries decisions
    assert "run_signal" in low or "parse_signal" in low  # chat signal is parseable
    assert "completion signal" in low
    assert "chat" in low and "file" in low         # two distinct destinations named
    # A structurally valid completion signal that run_signal.parse_signal accepts
    # under the reviewer's own phase must be documented in the prompt (and NOT be
    # confused with the verdict block, which lacks the signal's required keys).
    blocks = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", text)
    parsed = [rs.parse_signal("```json\n" + b + "\n```", "impl-plan-review")
              for b in blocks]
    assert any(s is not None and s.next_action == "ack" for s in parsed), (
        "prompt must document a parseable impl-plan-review completion signal"
    )


def test_prompt_categories_topics_closed_world_match_descriptor():
    """AC-11 (closed-world honesty): the prompt's DECLARED finding categories and
    decision topics (its Field-rules enumerations) equal EXACTLY the
    IMPL_PLAN_REVIEW descriptor's tuples — no fabricated category/topic outside the
    descriptor, and none the descriptor carries is omitted. Anchored to the REAL
    descriptor, so drift on either side fails."""
    text = _read(_REVIEWER)
    declared_cats = _enum_after(text, "category")
    declared_topics = _enum_after(text, "topic")
    assert declared_cats == set(ipr.IMPL_PLAN_REVIEW.finding_categories), (
        f"prompt's declared categories {declared_cats} must equal the descriptor's "
        f"{set(ipr.IMPL_PLAN_REVIEW.finding_categories)}"
    )
    assert declared_topics == set(ipr.IMPL_PLAN_REVIEW.decision_topics), (
        f"prompt's declared topics {declared_topics} must equal the descriptor's "
        f"{set(ipr.IMPL_PLAN_REVIEW.decision_topics)}"
    )
    # And no OTHER kind's distinct vocabulary leaked into the prompt (spec-review /
    # test-plan-review categories that are NOT also impl-plan categories).
    foreign = (set(sr.SPEC_REVIEW.finding_categories)
               | {"uncovered-ac", "weak-assertion", "missing-edge-case"}
               ) - set(ipr.IMPL_PLAN_REVIEW.finding_categories)
    assert declared_cats.isdisjoint(foreign), (
        f"prompt declared a foreign category: {declared_cats & foreign}"
    )


# ===========================================================================
# step-3 — wire consume at the ack + extend impl.md to a THIRD findings file + docs
# ===========================================================================

def _assessment_section(text: str) -> str:
    """The build-start «Assess the independent review findings» H2 section body,
    from its heading to just before the next H2. Empty string if absent."""
    m = re.search(
        r"(^##\s+Assess the independent review findings.*?)(?=^##\s)",
        text, re.S | re.M,
    )
    return m.group(1) if m else ""


def _three_subblocks(text: str) -> tuple[str, str, str]:
    """Split the assessment section into (spec-review, test-plan-review,
    impl-plan-review) sub-blocks around the two later findings-file anchors, so the
    three can be compared element-by-element."""
    section = _assessment_section(text)
    tp_idx = section.find(_TESTPLAN_FINDINGS_FILE)
    ip_idx = section.find(_IMPLPLAN_FINDINGS_FILE)
    if tp_idx == -1 or ip_idx == -1:
        return section, "", ""
    tp_start = section.rfind("\n", 0, tp_idx)
    ip_start = section.rfind("\n", 0, ip_idx)
    spec = section[:tp_start]
    tp = section[tp_start:ip_start]
    ip = section[ip_start:]
    return spec, tp, ip


def test_impl_reads_implplan_findings_file():
    """AC-7: impl.md's build-start assessment step names
    impl-plan-review-findings.json, instructs reading it, and pins it to the REAL
    schema + the five REAL impl-plan categories (no promised shape the file lacks)."""
    section = _assessment_section(_read(_IMPL))
    assert section, "impl.md must carry the «Assess the independent review findings» step"
    assert _IMPLPLAN_FINDINGS_FILE in section, (
        "the build-start assessment step must name impl-plan-review-findings.json"
    )
    _, _, ip = _three_subblocks(_read(_IMPL))
    assert ip, "the impl-plan-review sub-block must exist"
    assert "read" in ip.lower(), "the sub-block must instruct READING the file"
    for token in ("id", "category", "severity", "detail", "ref", "suggested_fix"):
        assert token in ip, f"impl-plan sub-block must name the schema field '{token}'"
    for cat in _IMPLPLAN_CATEGORIES:
        assert cat in ip, f"impl-plan sub-block must name the real category '{cat}'"


def test_impl_implplan_clause_symmetric_with_other_two():
    """AC-7 (C-002): the impl-plan-review clause carries every discipline element the
    spec-review AND test-plan-review clauses carry — one symmetric discipline for
    three reviewers, so the third block cannot drift weaker."""
    spec, tp, ip = _three_subblocks(_read(_IMPL))
    assert spec and tp and ip, "all three sub-blocks must exist"
    elements = (
        "fix", "won't-fix", "build-log.md", "high",
        "[!question]", "[!conflict]", "absent", "fabricate", "suggested_fix",
    )
    ip_low = ip.lower()
    for el in elements:
        if el in spec.lower() or el in tp.lower():
            assert el in ip_low, (
                f"the impl-plan-review clause is missing '{el}' the other clauses "
                f"carry — the three must not drift apart (C-002)"
            )


def test_impl_degrades_when_implplan_findings_absent():
    """AC-8: impl.md degrades when the file is absent — nothing to assess, proceed,
    do not fabricate findings."""
    _, _, ip = _three_subblocks(_read(_IMPL))
    low = ip.lower()
    assert "absent" in low, "the degrade rule keys on an absent file"
    assert "nothing to assess" in low
    assert "not fabricate" in low or "do not fabricate" in low


def test_ack_surfaces_and_records_implplan_review_on_persist(tmp_path, monkeypatch):
    """AC-5 / AC-6: the ack wire (`phase_completion._implplan_review_advisories`,
    persist=True) records impl-plan-review-findings.json and surfaces the routed
    decision + a collapsed findings count. Exercises the REAL helper against a
    fabricated ticket dir."""
    import phase_completion as pc

    (tmp_path / "impl-plan-review.md").write_text(
        "```json\n"
        '{"findings":[{"id":"F-1","category":"missing-step","severity":"high",'
        '"detail":"AC-3 has no step"}],'
        '"decisions_to_confirm":[{"id":"D-1","topic":"sequencing-tradeoff",'
        '"question":"parser first?","recommended":"yes"}]}\n```\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(pc, "klc_ticket_meta_file",
                        lambda t: tmp_path / "meta.json")
    monkeypatch.setattr(pc._lc, "read_meta_ro",
                        lambda t: {"track": "M", "risk_tags": []})

    advisories = pc._implplan_review_advisories("KLC-XXX", persist=True)
    assert (tmp_path / _IMPLPLAN_FINDINGS_FILE).exists()  # recorded on persist
    assert any(a.startswith("impl-plan-review[decision") for a in advisories), advisories
    assert any("finding(s) recorded" in a for a in advisories), advisories


def test_ack_probe_persist_false_writes_nothing(tmp_path, monkeypatch):
    """AC-6: the read-only probe (persist=False) surfaces the SAME advisories but
    writes nothing — the KLC-062 read-only-verb discipline, threaded to the seam."""
    import phase_completion as pc

    (tmp_path / "impl-plan-review.md").write_text(
        "```json\n"
        '{"findings":[{"id":"F-1","category":"untestable-step","severity":"low",'
        '"detail":"step-2 has no RED"}],"decisions_to_confirm":[]}\n```\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(pc, "klc_ticket_meta_file",
                        lambda t: tmp_path / "meta.json")
    monkeypatch.setattr(pc._lc, "read_meta_ro",
                        lambda t: {"track": "M", "risk_tags": []})

    advisories = pc._implplan_review_advisories("KLC-XXX", persist=False)
    assert advisories  # still surfaced
    assert not (tmp_path / _IMPLPLAN_FINDINGS_FILE).exists()  # but NOTHING written


def test_docs_name_build_assessment_of_implplan_findings():
    """AC-7 (doc honesty): docs/process.md AND core/agents/impl-plan-reviewer.md name
    the build agent (impl.md) as the consumer that reads and assesses
    impl-plan-review-findings.json at build — no claim outruns the wire."""
    process = _read(_PROCESS)
    reviewer = _read(_REVIEWER)

    assert _IMPLPLAN_FINDINGS_FILE in process, (
        "docs/process.md must name impl-plan-review-findings.json"
    )
    p_low = process.lower()
    assert "impl.md" in p_low, "docs/process.md must name the build agent impl.md"
    assert "build" in p_low and "assess" in p_low

    r_low = reviewer.lower()
    assert "impl.md" in r_low, (
        "impl-plan-reviewer.md must name the build agent that assesses its findings"
    )
    assert _IMPLPLAN_FINDINGS_FILE in reviewer


def test_work_agents_document_the_reviewer_spawn():
    """AC-5/AC-9 (spawn honesty): the reviewer is spawn-documented in the WORK
    agents that finalize impl-plan.md — design.md (M/L, full) and discovery-lite.md
    (S, cascade) — exactly as KLC-084 documented spec-review in discovery-lite.md and
    KLC-085 documented test-plan-review in test-planner.md. Without this the
    orchestrator never spawns the reviewer, no impl-plan-review.md is ever produced,
    and every M/L design ack would surface a spurious 'expected but not found'
    degrade note — the consume side would have no producer."""
    for path, track_word in ((_DESIGN, "full"), (_DISCOVERY_LITE, "cascade")):
        text = _read(path)
        low = text.lower()
        assert "impl-plan-reviewer.md" in low, (
            f"{path.name} must document spawning core/agents/impl-plan-reviewer.md"
        )
        assert "impl-plan-review.md" in low, (
            f"{path.name} must name the reviewer's output file impl-plan-review.md"
        )
        assert "orchestrator" in low and "spawn" in low, (
            f"{path.name} must state the orchestrator (not the agent) spawns it"
        )
        assert _IMPLPLAN_FINDINGS_FILE in text, (
            f"{path.name} must name impl-plan-review-findings.json (the recorded file)"
        )
        assert track_word in low, (
            f"{path.name} must state its track behaviour ('{track_word}')"
        )


def test_implplan_binding_degrades_without_reviewer_output(tmp_path):
    """AC-8/AC-9 (impl-plan binding degrade): a review-expected track (M → full →
    should_run True) with NO impl-plan-review.md degrades to a single surfaced note
    and writes nothing — pinned on the impl-plan binding directly, not only through
    the shared seam."""
    advisories, findings = ipr.consume(tmp_path, "M", {"risk_tags": []}, persist=True)
    assert findings == []
    assert not (tmp_path / _IMPLPLAN_FINDINGS_FILE).exists()
    assert len(advisories) == 1 and advisories[0].startswith("impl-plan-review:"), advisories
    # And XS (skip) is silent — no note, no write.
    xs_adv, xs_find = ipr.consume(tmp_path, "XS", {"risk_tags": []}, persist=True)
    assert xs_adv == [] and xs_find == []


def _section(text: str, heading: str) -> str:
    """The body of the `## <heading>` section, to the next H2. '' if absent."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s)", text, re.S | re.M)
    return m.group(1) if m else ""


def test_prompt_cascade_names_only_risk_tags_at_implplan_phase():
    """codex-P2 (prompt honesty): the S-cascade wording must match what the code
    actually passes and what is AVAILABLE at the impl-plan phase. The ack that
    finalizes impl-plan.md (design / discovery-lite) runs BEFORE any code diff, and
    `_implplan_review_advisories` passes ONLY `{"risk_tags": …}`. So the only active
    escalation signal here is a risk_tag; scope-expansion and sentinel hits (which
    need a diff) CANNOT fire yet — exactly the honest caveat discovery-lite.md
    already carries for the spec reviewer. The prompt must say so, not over-claim
    that scope-expansion / sentinel fire at this phase."""
    section = _section(_read(_REVIEWER), "Track scaling")
    assert section, "impl-plan-reviewer.md must have a ## Track scaling section"
    low = section.lower()
    # The active trigger IS a risk tag.
    assert "risk_tag" in low or "risk tag" in low, "risk_tags is the active trigger"
    # The honest caveat: no diff yet, so scope-expansion / sentinel do NOT fire here.
    assert "no diff" in low, "must state there is no diff yet at the impl-plan phase"
    assert "do not fire" in low or "does not fire" in low or "not fire" in low, (
        "must state scope-expansion / sentinel signals do NOT fire at this phase"
    )
    # And it must name what does not fire, so the caveat is concrete.
    assert "scope-expansion" in low or "sentinel" in low
