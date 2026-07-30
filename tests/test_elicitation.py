#!/usr/bin/env python3
"""Tests for core/skills/elicitation.py — the E-02 elicitation engine (KLC-088).

The engine consumes three already-shipped seams unchanged and is deliberately
deterministic (no LLM call, mirroring spec_review.py / spec_selfcheck.py):

  * coverage_taxonomy.for_track / by_id — the SINGLE source for the mandatory
    coverage categories and their min_track floors (never a second YAML parse).
  * spec_saoc.parse_acs               — AC parsing for the functional-scope scan.
  * spec_review.DecisionToConfirm / validate — the decision shape the routed
    decisions_to_confirm reuse verbatim.

The suite is split by build step: step-1 (coverage scan), step-2 (prioritised +
capped queue), step-3 (routing + degrade). Negative paths, not just happy-path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import coverage_taxonomy  # noqa: E402
import spec_saoc  # noqa: E402
import spec_review  # noqa: E402
import elicitation  # noqa: E402


# --- sample draft specs -----------------------------------------------------

# A full spec: Goals heading + SAOC acceptance criteria + an explicit Non-goals
# heading, plus a data section — functional-scope should read Clear.
_FULL_SPEC = """\
# Widget — draft spec

## Goals
Ship a widget that greets a named user and records the greeting.

## Domain & Data Model
The core entities are the User and the Greeting, each with a stable id and a
lifecycle state.

## Acceptance Criteria
- [ ] AC-1: the widget · greets · the named user · when a name is supplied
- [ ] AC-2: the widget · records · the greeting · when the greeting is emitted

## Non-goals
- No authentication, no persistence beyond the in-memory store.
"""

# The same spec with its Acceptance Criteria section removed: functional-scope
# has a Goals + Non-goals heading but no ACs, so it should read Partial.
_SPEC_NO_ACS = """\
# Widget — draft spec

## Goals
Ship a widget that greets a named user and records the greeting.

## Non-goals
- No authentication, no persistence.
"""

# A minimal spec about a pure function with no data/domain vocabulary at all:
# domain-data-model has neither a section nor any evidencing token → Missing.
_SPEC_NO_DOMAIN = """\
# Greeter — draft spec

## Goals
Return the string "hello" when called.

## Acceptance Criteria
- [ ] AC-1: the greeter · returns · the string hello · when it is invoked

## Non-goals
- Nothing else.
"""


# --- step-1: the coverage scan ----------------------------------------------

def test_scan_reads_categories_via_for_track(monkeypatch):
    """AC-1: the scanned category id-set is EXACTLY coverage_taxonomy.for_track's
    return — proving the engine reads only through it and never re-parses the
    YAML (a re-parse would yield the real ten categories, not this subset)."""
    fake = [{"id": "functional-scope", "min_track": "XS", "sub_checks": ["core-goals"]}]
    monkeypatch.setattr(coverage_taxonomy, "for_track", lambda track: list(fake))

    result = elicitation.scan_coverage(_FULL_SPEC, "S")

    assert {c.id for c in result} == {"functional-scope"}


def test_scan_classifies_clear_partial_missing():
    """AC-2: a full Goals+ACs+Non-goals section → functional-scope Clear; the
    same spec without ACs → Partial; an absent data section → domain Missing."""
    def _status(coverage, cat_id):
        return next(c.status for c in coverage if c.id == cat_id)

    full = elicitation.scan_coverage(_FULL_SPEC, "S")
    assert _status(full, "functional-scope") == "Clear"

    thin = elicitation.scan_coverage(_SPEC_NO_ACS, "S")
    assert _status(thin, "functional-scope") == "Partial"

    nodomain = elicitation.scan_coverage(_SPEC_NO_DOMAIN, "S")
    assert _status(nodomain, "domain-data-model") == "Missing"


def test_scan_uses_spec_saoc_for_acs(monkeypatch):
    """AC-2: the scan reuses spec_saoc.parse_acs for the AC evidence. Spy on it:
    when it is stubbed to report NO acs, functional-scope drops from Clear to
    Partial, proving the classification flows through the seam."""
    calls = {"n": 0}
    real = spec_saoc.parse_acs

    def spy(text):
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(spec_saoc, "parse_acs", spy)
    full = elicitation.scan_coverage(_FULL_SPEC, "S")
    assert calls["n"] >= 1
    assert next(c.status for c in full if c.id == "functional-scope") == "Clear"

    monkeypatch.setattr(spec_saoc, "parse_acs", lambda text: [])
    thin = elicitation.scan_coverage(_FULL_SPEC, "S")
    assert next(c.status for c in thin if c.id == "functional-scope") == "Partial"


def test_scan_empty_spec_degrades_to_empty_map():
    """AC-9 / C-002: an empty or whitespace-only draft spec yields an empty
    coverage map, never a raise."""
    assert elicitation.scan_coverage("", "S") == []
    assert elicitation.scan_coverage("   \n\t ", "M") == []


# --- step-2: the prioritised + track-capped question queue -------------------

# The six categories mandatory at track S (min_track floor XS or S). Used to
# build coverage inputs directly, so the queue tests do not depend on the scan.
_S_CATEGORIES = [
    "functional-scope", "domain-data-model", "interaction-ux",
    "edge-failure", "completion-signals", "misc-placeholders",
]


def _cov(pairs):
    return [elicitation.CategoryCoverage(id=i, status=s) for i, s in pairs]


def test_clear_category_scores_zero_and_is_dropped():
    """AC-3: a Clear category has zero Uncertainty, so it scores zero and never
    appears in the queue; only the unresolved category survives."""
    coverage = _cov([("functional-scope", elicitation.CLEAR),
                     ("domain-data-model", elicitation.MISSING)])
    queue = elicitation.build_question_queue(coverage, "S")
    ids = [q.category_id for q in queue]
    assert "functional-scope" not in ids
    assert "domain-data-model" in ids
    # And the Clear category, were it scored, is exactly zero.
    assert all(q.score > 0 for q in queue)


def test_missing_outranks_same_impact_partial():
    """AC-3: for two categories of equal Impact (same min_track floor S), the
    Missing one (Uncertainty 2) outranks the Partial one (Uncertainty 1)."""
    coverage = _cov([("interaction-ux", elicitation.PARTIAL),   # impact 3, u1 → 3
                     ("domain-data-model", elicitation.MISSING)])  # impact 3, u2 → 6
    queue = elicitation.build_question_queue(coverage, "M")
    assert queue[0].category_id == "domain-data-model"
    assert queue[1].category_id == "interaction-ux"


def test_queue_capped_three_on_S_five_on_M():
    """AC-4: with more unresolved categories than the cap admits, the queue is
    truncated to at most three on track S and at most five on M."""
    coverage = _cov([(cid, elicitation.MISSING) for cid in _S_CATEGORIES])  # six
    assert len(elicitation.build_question_queue(coverage, "S")) == 3
    assert len(elicitation.build_question_queue(coverage, "M")) == 5
    # The cap keeps the highest-scoring questions — the XS-floor (Impact 4)
    # categories must survive the S cap over the S-floor (Impact 3) ones.
    kept = {q.category_id for q in elicitation.build_question_queue(coverage, "S")}
    assert "functional-scope" in kept  # XS floor, Missing → top score


def test_each_question_has_interrogative_why_and_recommended():
    """AC-5: every emitted Question carries a real interrogative ending in '?',
    a non-empty why-it-matters, and a non-empty recommended default."""
    coverage = _cov([(cid, elicitation.MISSING) for cid in _S_CATEGORIES])
    queue = elicitation.build_question_queue(coverage, "M")
    assert queue  # non-empty
    for q in queue:
        assert q.interrogative.strip().endswith("?")
        assert q.why.strip()
        assert q.recommended.strip()


def test_risk_tag_escalates_aligned_category_impact():
    """Q-002: an aligned risk_tag lifts a category's Impact above its floor-only
    base — a `security` tag raises `nfr` above where it would otherwise score."""
    coverage = _cov([("nfr", elicitation.MISSING)])
    base = elicitation.build_question_queue(coverage, "M")[0]
    lifted = elicitation.build_question_queue(
        coverage, "M", signals={"risk_tags": ["security"]})[0]
    assert lifted.impact > base.impact
    assert lifted.score > base.score


# --- step-3: routing (marker / decision_to_confirm / Assumptions) + degrade ---

def _q(category_id, score, *, defensible, recommended, topic="scope"):
    return elicitation.Question(
        category_id=category_id,
        interrogative=f"What about {category_id}?",
        why="it matters",
        recommended=recommended,
        impact=4,
        uncertainty=2,
        score=score,
        defensible_default=defensible,
        topic=topic,
    )


def test_high_impact_no_default_routes_to_marker():
    """AC-6 / Q-001: a high-impact dimension with NO defensible default routes to
    a BLOCKING [NEEDS CLARIFICATION] marker — it is NOT silently downgraded."""
    q = _q("functional-scope", 8, defensible=False,
           recommended="(no safe default)")
    res = elicitation.route([q], [], "S")
    assert res.markers and any("[NEEDS CLARIFICATION" in m for m in res.markers)
    assert res.decisions == []
    assert res.assumptions == []


def test_high_impact_with_default_routes_to_decision_to_confirm():
    """AC-6 / Q-001: a high-impact dimension WITH a defensible default routes to a
    non-blocking decision_to_confirm carrying the mandatory recommended answer."""
    q = _q("domain-data-model", 6, defensible=True,
           recommended="Assume one entity with a single id", topic="scope")
    res = elicitation.route([q], [], "M")
    assert res.markers == []
    assert len(res.decisions) == 1
    dec = res.decisions[0]
    assert isinstance(dec, spec_review.DecisionToConfirm)
    assert dec.recommended.strip()


def test_decisions_conform_to_spec_review_validate():
    """AC-8: the routed decisions satisfy KLC-084's schema unchanged —
    spec_review.validate returns no error over them."""
    qs = [
        _q("domain-data-model", 6, defensible=True, recommended="assume A", topic="scope"),
        _q("nfr", 5, defensible=True, recommended="assume B", topic="tradeoff"),
        _q("terminology", 4, defensible=True, recommended="assume C", topic="ambiguous-intent"),
    ]
    res = elicitation.route(qs, [], "M")
    output = spec_review.ReviewOutput(decisions_to_confirm=res.decisions)
    assert spec_review.validate(output) == []


def test_low_impact_routes_to_assumptions_line():
    """AC-7: a below-threshold dimension is recorded as an ## Assumptions line
    stating the guessed default — with no marker and no decision."""
    q = _q("misc-placeholders", 2, defensible=True,
           recommended="Assume no open placeholders remain")
    res = elicitation.route([q], [], "S")
    assert res.markers == []
    assert res.decisions == []
    assert res.assumptions and any("misc-placeholders" in a for a in res.assumptions)
    assert any("Assume no open placeholders" in a for a in res.assumptions)


def test_elicit_degrades_on_absent_taxonomy_and_unknown_track(monkeypatch):
    """AC-9 / C-002: elicit() over an absent taxonomy or an unknown track returns
    an empty result — every list empty — without raising."""
    # Unknown track: real for_track returns [] for "XL".
    res = elicitation.elicit(_FULL_SPEC, "XL")
    assert res.coverage == [] and res.questions == []
    assert res.markers == [] and res.decisions == [] and res.assumptions == []

    # Absent taxonomy: for_track degrades to []; the whole engine is a clean no-op.
    monkeypatch.setattr(coverage_taxonomy, "for_track", lambda track: [])
    res2 = elicitation.elicit(_FULL_SPEC, "M")
    assert res2.coverage == [] and res2.questions == []
    assert res2.markers == [] and res2.decisions == [] and res2.assumptions == []


def test_elicit_end_to_end_produces_routed_outputs():
    """The elicit() convenience wires scan → queue → route over a real spec: it
    returns a populated coverage map and a routed result whose parts are lists."""
    res = elicitation.elicit(_SPEC_NO_DOMAIN, "S")
    assert res.coverage  # scanned something
    assert isinstance(res.markers, list)
    assert isinstance(res.decisions, list)
    assert isinstance(res.assumptions, list)
    # Every routed decision still conforms to the KLC-084 schema.
    assert spec_review.validate(
        spec_review.ReviewOutput(decisions_to_confirm=res.decisions)) == []


# --- independent-review fixes (KLC-088) -------------------------------------

import re as _re_fixes  # noqa: E402

# A minimal non-empty spec that carries NO coverage-category vocabulary, so every
# mandatory category classifies unresolved (Missing) — used to prove the cap
# never drops a dimension from the routed record.
_BARE_SPEC = "# Ticket\n\nMake it work.\n"


def _routed_ids(res):
    """The set of category ids that landed in markers ∪ decisions ∪ assumptions."""
    ids = set()
    for m in res.markers:
        mm = _re_fixes.search(r"\[NEEDS CLARIFICATION \(([^)]+)\)", m)
        if mm:
            ids.add(mm.group(1))
    for d in res.decisions:
        ids.add(d.ref)
    for a in res.assumptions:
        ids.add(a.split(":", 1)[0].lstrip("- ").strip())
    return ids


def test_route_covers_every_unresolved_dim_regardless_of_cap():
    """FIX 1 (HIGH): the question cap bounds only how many questions go to the
    human; routing/recording must cover EVERY unresolved category. An all-Missing
    spec has more categories than the cap, yet none may be silently dropped."""
    for track in ("S", "M"):
        res = elicitation.elicit(_BARE_SPEC, track)
        unresolved = {c.id for c in res.coverage
                      if c.status in (elicitation.PARTIAL, elicitation.MISSING)}
        assert unresolved  # the bare spec leaves every category unresolved
        assert _routed_ids(res) == unresolved  # set-complete: nothing dropped
        # And the human-facing question queue still respects the cap.
        assert len(res.questions) <= (3 if track == "S" else 5)


def test_non_goal_heading_alone_does_not_make_functional_scope_clear():
    """FIX 2 (codex-P2): a Non-goals heading must NOT count as a goals section. A
    spec with ACs + Non-goals but no goals section → functional-scope Missing (the
    ticket's only blocking path), not falsely Clear."""
    spec = (
        "# Thing\n\n"
        "## Acceptance Criteria\n"
        "- [ ] AC-1: the thing · does · a job · when it is invoked\n\n"
        "## Non-goals\n- nothing else\n"
    )
    cov = elicitation.scan_coverage(spec, "S")
    assert next(c.status for c in cov if c.id == "functional-scope") == elicitation.MISSING
    res = elicitation.elicit(spec, "S")
    assert any("functional-scope" in m for m in res.markers)


def test_track_normalized_before_taxonomy_lookup():
    """FIX 3 (codex-P2): a lowercase / padded track resolves identically to the
    canonical one — elicitation is never skipped over a cosmetic track string."""
    canon = elicitation.elicit(_FULL_SPEC, "S")
    assert canon.coverage
    for variant in ("s", " S ", "s\t"):
        got = elicitation.elicit(_FULL_SPEC, variant)
        assert {c.id for c in got.coverage} == {c.id for c in canon.coverage}
    assert elicitation.scan_coverage(_FULL_SPEC, "s")  # non-empty, not skipped


def test_substantive_category_outranks_housekeeping_at_same_track():
    """FIX 4 (LOW): the questions put to the human lead with substance — a
    substantive Missing category outranks the (sole) housekeeping category,
    misc-placeholders. completion-signals is SUBSTANTIVE (measurable DoD), so it
    is NOT demoted and need not be out-ranked (FIX A)."""
    coverage = _cov([("misc-placeholders", elicitation.MISSING),
                     ("completion-signals", elicitation.MISSING),
                     ("domain-data-model", elicitation.MISSING),
                     ("edge-failure", elicitation.MISSING)])
    ids = [q.category_id for q in elicitation.build_question_queue(coverage, "M")]
    assert ids.index("domain-data-model") < ids.index("misc-placeholders")
    assert ids.index("edge-failure") < ids.index("misc-placeholders")
    assert ids.index("completion-signals") < ids.index("misc-placeholders")


def _escalated_ids(res):
    """Category ids that ESCALATED (markers ∪ decisions) — excludes assumptions."""
    ids = set(d.ref for d in res.decisions)
    for m in res.markers:
        mm = _re_fixes.search(r"\[NEEDS CLARIFICATION \(([^)]+)\)", m)
        if mm:
            ids.add(mm.group(1))
    return ids


def test_goals_only_spec_surfaces_missing_acceptance_criteria():
    """FIX A (P2): a Goals-only spec (no AC-N lines) must still be asked for its
    acceptance criteria / measurable Definition of Done — the completion-signals
    gap escalates (decision/marker), it is never a low-impact assumption or absent.
    And functional-scope's own recommendation stays honest about the ACs gap."""
    spec = "# Thing\n\n## Goals\nBuild a thing that greets the user.\n"
    res = elicitation.elicit(spec, "S")
    assert "completion-signals" in _escalated_ids(res)
    fs = next(d for d in res.decisions if d.ref == "functional-scope")
    # honest: when the missing leg is the ACs, do NOT recommend a scope boundary.
    assert "out of scope" not in fs.recommended.lower()
    assert "criteria" in fs.recommended.lower()


def test_combined_goals_and_non_goals_heading_counts_as_goals():
    """FIX B (P3): a combined `## Goals and Non-goals` heading names goals even
    though it also names non-goals — it must NOT be rejected as goal evidence, so
    functional-scope is not spuriously Missing / blocked."""
    spec = (
        "# Thing\n\n"
        "## Goals and Non-goals\n"
        "Greet the user. Out of scope: persistence.\n\n"
        "## Acceptance Criteria\n"
        "- [ ] AC-1: the thing · greets · the user · when a name is given\n"
    )
    status = next(c.status for c in elicitation.scan_coverage(spec, "S")
                  if c.id == "functional-scope")
    assert status != elicitation.MISSING
    assert not any("functional-scope" in m
                   for m in elicitation.elicit(spec, "S").markers)


@pytest.mark.parametrize("heading,is_goal", [
    ("Goals", True),
    ("Objectives", True),
    ("Goals and Non-goals", True),          # standalone "goals" survives
    ("Non-goals and Goals", True),          # order-independent
    ("Non-goals", False),
    ("Out of scope", False),
    ("Out-of-scope", False),
    ("Out-of-scope goals", False),          # qualifier+goalword removed as a unit
    ("Non-goal objectives", False),         # qualifier+goalword removed as a unit
    ("Scope", True),                        # a bare scope section is goal-adjacent
    # FIX 1: a boundary qualifier scopes over the WHOLE conjunction of goal words.
    ("Out-of-scope goals and objectives", False),   # entire conjunction removed
    ("Non-goal goals and behaviors", False),        # entire conjunction removed
    ("Goals, Objectives and Scope", True),          # genuine goals list — NOT eaten
    # HARDENING 2: exclusion forms are boundary qualifiers, not goal evidence.
    ("Scope exclusions", False),
    ("Exclusions from scope", False),
    ("Exclusions", False),
    # HARDENING 4: ANY punctuation between a boundary qualifier and its goal
    # word(s) is consumed as a unit (colon, em dash, comma, ...), not just space.
    ("Out-of-scope: goals and objectives", False),
    ("Out of scope — goals", False),
    ("Non-goals: objectives", False),
    ("Non-goals: objectives, behaviors", False),
    ("Goals: overview", True),      # colon after a REAL goals word — still evidence
])
def test_names_goals_matrix(heading, is_goal):
    """FIX C (P2): the goal-evidence predicate is robust in ONE pass — a boundary
    qualifier directly followed by a goal word ("Out-of-scope goals") is removed as
    a unit, so a PURE boundary heading is never misread as a goals section (which
    would suppress the blocking clarification when the core goal is missing)."""
    assert elicitation._names_goals(heading.lower()) is is_goal


# The full goal-word vocabulary that must be accepted as goal evidence — a strict
# SUPERSET of the pre-round-3 tokens (goal(s)/objective(s)/scope/behavior/
# behaviour) plus purpose. A parametrized guard so a refactor can't silently drop
# one again (FIX D).
_GOAL_VOCAB = ["goal", "goals", "objective", "objectives", "purpose", "scope",
               "behavior", "behaviour", "behaviors", "behaviours"]


@pytest.mark.parametrize("token", _GOAL_VOCAB)
def test_every_goal_vocab_token_is_goal_evidence(token):
    """FIX D (P2): every accepted goal word, as a bare heading, is goal-evidence."""
    assert elicitation._names_goals(token) is True


@pytest.mark.parametrize("heading", ["Behavior", "Expected Behaviour"])
def test_behavior_heading_is_functional_scope_evidence(heading):
    """FIX D (P2): a Behavior/Behaviour heading is functional-scope goal evidence
    — a spec with it + ACs must NOT classify functional-scope Missing / block."""
    spec = (
        f"# Thing\n\n## {heading}\nThe thing greets the user.\n\n"
        "## Acceptance Criteria\n"
        "- [ ] AC-1: the thing · greets · the user · when a name is given\n"
    )
    status = next(c.status for c in elicitation.scan_coverage(spec, "S")
                  if c.id == "functional-scope")
    assert status != elicitation.MISSING
    assert not any("functional-scope" in m
                   for m in elicitation.elicit(spec, "S").markers)


def test_impact_degrades_on_non_scalar_min_track(monkeypatch):
    """FIX 5 (LOW): a malformed (non-scalar) min_track must not crash the public
    build_question_queue — it degrades to the default rank, like the reader."""
    monkeypatch.setattr(coverage_taxonomy, "by_id",
                        lambda cid: {"id": cid, "min_track": ["XS"]})
    queue = elicitation.build_question_queue(
        _cov([("domain-data-model", elicitation.MISSING)]), "M")
    assert len(queue) == 1  # no raise


def test_partial_functional_scope_routes_to_decision_not_block():
    """FIX 6 (LOW): a goal that is present but lacks an explicit boundary is
    Partial → a decision_to_confirm with a real recommendation, NOT a block."""
    spec = (
        "# Thing\n\n"
        "## Goals\nBuild a thing that greets the user.\n\n"
        "## Acceptance Criteria\n"
        "- [ ] AC-1: the thing · greets · the user · when a name is given\n"
    )
    cov = elicitation.scan_coverage(spec, "S")
    assert next(c.status for c in cov if c.id == "functional-scope") == elicitation.PARTIAL
    res = elicitation.elicit(spec, "S")
    assert not any("functional-scope" in m for m in res.markers)
    dec = next(d for d in res.decisions if d.ref == "functional-scope")
    assert dec.recommended.strip() and "no safe default" not in dec.recommended


def test_scan_degrades_on_scalar_sub_checks(monkeypatch):
    """FIX 2 (P2): a loadable override with a SCALAR sub_checks (not a list) must
    not crash scan_coverage / elicit — a non-list is normalized to [] so the
    per-category scan stays degrade-not-fail (an int scalar would otherwise raise
    TypeError on iteration)."""
    monkeypatch.setattr(coverage_taxonomy, "for_track", lambda track: [
        {"id": "domain-data-model", "min_track": "S", "sub_checks": 5},
        {"id": "edge-failure", "min_track": "S", "sub_checks": "boundary"},
    ])
    cov = elicitation.scan_coverage(_FULL_SPEC, "S")  # must not raise
    assert isinstance(cov, list) and {c.id for c in cov} == {
        "domain-data-model", "edge-failure"}
    res = elicitation.elicit(_FULL_SPEC, "S")  # must not raise
    assert isinstance(res.coverage, list)


def test_route_synthesis_applies_risk_boost_to_cap_dropped_category():
    """P2: a category CUT from the capped question queue must be routed on the
    SAME (risk-boosted) score as if it had made the cut — route()'s synthesis
    threads `signals` so a risk-aligned cap-dropped dimension reaches the ack gate
    as a decision, not a silent low-impact assumption. Its routing must not depend
    on whether it happened to fit under the human question cap."""
    # domain-data-model is Partial (a bare "data" mention, no domain heading) and
    # is scored below the S cap's top-3 (functional-scope / completion-signals /
    # interaction|edge are all higher), so it is cut from res.questions either way.
    spec = "# Widget\n\nThis widget processes some data for the operator.\n"

    base = elicitation.elicit(spec, "S")
    assert "domain-data-model" not in {q.category_id for q in base.questions}
    # base impact 3 × Partial 1 = 3 → below threshold → an assumption line.
    assert not any(d.ref == "domain-data-model" for d in base.decisions)
    assert any(a.startswith("- domain-data-model:") for a in base.assumptions)

    boosted = elicitation.elicit(spec, "S", signals={"risk_tags": ["data"]})
    assert "domain-data-model" not in {q.category_id for q in boosted.questions}
    # boosted impact 4 × Partial 1 = 4 → at threshold → a decision_to_confirm.
    assert any(d.ref == "domain-data-model" for d in boosted.decisions)
    assert not any(a.startswith("- domain-data-model:") for a in boosted.assumptions)


@pytest.mark.parametrize("word,category,track", [
    ("build building rebuild", "interaction-ux", "S"),   # 'ui' inside build
    ("auxiliary helpers", "interaction-ux", "S"),         # 'ux' inside auxiliary
    ("rapid prototyping", "integration-external", "M"),   # 'api' inside rapid
    ("condone the plan", "completion-signals", "M"),      # 'done' inside condone
])
def test_short_keyword_no_substring_false_hit(word, category, track):
    """HARDENING 1 (P2): keyword/sub-check matching is whole-token (word-boundary),
    so a short keyword is never satisfied by being a substring of an unrelated word
    (e.g. 'ui' in 'build'). A spec whose only would-be signal is such a substring
    leaves the category Missing, not falsely Partial."""
    spec = f"# T\n\n## Overview\nWe {word} the tool.\n"
    cov = elicitation.scan_coverage(spec, track)
    status = next(c.status for c in cov if c.id == category)
    assert status == elicitation.MISSING


def test_empty_ac_stub_does_not_satisfy_success_criteria_leg():
    """HARDENING 3 (P2): an empty `- [ ] AC-1:` stub is NOT real acceptance-criteria
    content, so functional-scope must not read Clear on the success-criteria leg —
    the gap is surfaced (Partial → a decision asking for the criteria), not silently
    Clear even with Goals + Non-goals present."""
    spec = (
        "# Thing\n\n"
        "## Goals\nBuild a greeter.\n\n"
        "## Acceptance Criteria\n- [ ] AC-1:\n\n"
        "## Non-goals\n- nothing else\n"
    )
    status = next(c.status for c in elicitation.scan_coverage(spec, "S")
                  if c.id == "functional-scope")
    assert status != elicitation.CLEAR
    res = elicitation.elicit(spec, "S")
    fs = next(d for d in res.decisions if d.ref == "functional-scope")
    assert "criteria" in fs.recommended.lower()  # honest: the ACs are the gap


@pytest.mark.parametrize("body", [
    "## Open Questions\n- What auth model should we use?\n",
    "\nTODO: decide the storage backend.\n",
    "\nThe schema is TBD / FIXME before launch.\n",
    # Strong multi-hit case: an Open Questions section naming TODO markers AND
    # placeholders evidences every sub_check → under the OLD positive scan this
    # read Clear and was omitted. Inverted polarity must route it.
    "## Open Questions\n- TODO markers and placeholders remain.\n",
    # Loose-end MARKERS the generic misc keywords missed entirely (FIX B set).
    "\n[NEEDS CLARIFICATION: which auth model?]\n",
    "\nThe rate limit is ??? for now.\n",
    # Plural marker forms used to group unresolved work (round-11 re-review).
    "\nTODOs:\n- decide storage\n- decide auth\n",
    "\nFIXMEs: the retry path and the timeout.\n",
])
def test_misc_placeholders_is_inverted_a_hit_is_unresolved(body):
    """P2 (semantic): misc-placeholders is a NEGATIVE-signal category — the
    presence of an open question / TODO / placeholder is the loose end it exists to
    catch, so a hit must classify it UNRESOLVED and route it, NOT read Clear and be
    omitted."""
    spec = f"# Thing\n\n## Goals\nBuild it.\n{body}"
    cov = elicitation.scan_coverage(spec, "S")
    status = next(c.status for c in cov if c.id == "misc-placeholders")
    assert status != elicitation.CLEAR
    res = elicitation.elicit(spec, "S")
    assert "misc-placeholders" in _routed_ids(res)  # surfaced, not dropped


def test_misc_placeholders_clear_when_no_loose_ends():
    """P2 (semantic): the ABSENCE of open questions / TODOs / placeholders is the
    Clear (good) state for the inverted category — it does not surface."""
    spec = (
        "# Thing\n\n## Goals\nBuild it.\n\n"
        "## Acceptance Criteria\n- [ ] AC-1: the thing · does · x · when it is run\n"
    )
    cov = elicitation.scan_coverage(spec, "S")
    assert next(c.status for c in cov if c.id == "misc-placeholders") == elicitation.CLEAR
    res = elicitation.elicit(spec, "S")
    assert "misc-placeholders" not in _routed_ids(res)  # good state → omitted


@pytest.mark.parametrize("prose", [
    "Open the modal and click save.",          # 'open' is not a loose end
    "The map shows markers for each site.",     # 'markers' is not a loose end
    "Questions about pricing go to sales.",     # bare 'questions' is not a loose end
])
def test_misc_placeholders_no_false_positive_on_component_words(prose):
    """FIX B (P2): misc-placeholders matches ACTUAL loose-end markers (todo, tbd,
    fixme, xxx, ???, `[NEEDS CLARIFICATION]`, the phrase 'open questions',
    placeholder) — NOT the component words of its compound sub_checks. Ordinary
    prose ('open the modal', a map's 'markers') must not be flagged as a loose end
    for this INVERTED category (a false positive here is the costly direction)."""
    spec = (
        "# Thing\n\n## Goals\nBuild it.\n\n"
        "## Acceptance Criteria\n- [ ] AC-1: the thing · does · x · when it is run\n\n"
        f"## Notes\n{prose}\n"
    )
    cov = elicitation.scan_coverage(spec, "S")
    assert next(c.status for c in cov if c.id == "misc-placeholders") == elicitation.CLEAR
    res = elicitation.elicit(spec, "S")
    assert "misc-placeholders" not in _routed_ids(res)


def test_completion_signals_not_cleared_by_bare_acceptance_heading():
    """FIX A (P2): a bare `## Acceptance Criteria` heading with only an empty
    `- [ ] AC-1:` stub must NOT clear completion-signals — the mere heading /
    words 'acceptance'/'criteria' are not real done-criteria, so the high-impact
    criteria question still surfaces."""
    spec = (
        "# Thing\n\n## Goals\nBuild it.\n\n"
        "## Acceptance Criteria\n- [ ] AC-1:\n"
    )
    cov = elicitation.scan_coverage(spec, "M")
    assert next(c.status for c in cov if c.id == "completion-signals") != elicitation.CLEAR
    res = elicitation.elicit(spec, "M")
    assert "completion-signals" in _escalated_ids(res)  # surfaces (decision/marker)


def test_completion_signals_clear_with_real_ac_body():
    """FIX A (P2): a content-bearing acceptance criterion IS a real completion
    signal → completion-signals reads Clear and does not surface."""
    spec = (
        "# Thing\n\n## Goals\nBuild it.\n\n"
        "## Acceptance Criteria\n- [ ] AC-1: the thing · does · x · when it is run\n"
    )
    cov = elicitation.scan_coverage(spec, "M")
    assert next(c.status for c in cov if c.id == "completion-signals") == elicitation.CLEAR


def test_frontmatter_metadata_not_scanned_as_body_content():
    """P2: a leading YAML frontmatter block is METADATA, not spec body — its values
    must not count as coverage evidence. An M-track spec with `risk_tags:[security]`
    in frontmatter but NO NFR/security body section → nfr is Missing (not Partial
    from the frontmatter word 'security'), so the risk-boosted score reaches the ack
    gate as a decision_to_confirm, NOT a downgraded assumption. The boost itself
    comes from the `signals=` argument, so stripping frontmatter never loses it."""
    spec = (
        "---\n"
        "ticket: KLC-999\n"
        "risk_tags: [security]\n"
        "track: M\n"
        "---\n\n"
        "# Thing\n\n## Goals\nBuild a service.\n"
    )
    cov = elicitation.scan_coverage(spec, "M")
    assert next(c.status for c in cov if c.id == "nfr") == elicitation.MISSING
    res = elicitation.elicit(spec, "M", signals={"risk_tags": ["security"]})
    assert any(d.ref == "nfr" for d in res.decisions)
    assert not any(a.startswith("- nfr:") for a in res.assumptions)


def test_mid_body_horizontal_rule_not_stripped_as_frontmatter():
    """A `---` thematic break in the BODY (not at the very start) must NOT be
    mistaken for a frontmatter fence — nothing before it is stripped."""
    spec = "# Thing\n\n## Goals\nBuild it.\n\n---\n\n## Notes\nmore.\n"
    assert elicitation._strip_frontmatter(spec) == spec
    # And a real leading frontmatter block IS stripped, body retained.
    fm = "---\nkey: value\n---\n\n# Body\ntext\n"
    stripped = elicitation._strip_frontmatter(fm)
    assert "key: value" not in stripped and "# Body" in stripped
