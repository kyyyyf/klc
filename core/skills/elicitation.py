#!/usr/bin/env python3
"""elicitation.py — the coverage-driven question-generation engine (E-02, KLC-088).

`discovery.md` knows HOW to ask (a Socratic sub-protocol, AskUserQuestion,
present-and-pick) but has no systematic checklist of WHAT to interrogate, so
completeness is by luck, not by construction. This engine supplies the checklist:
it reads the track-mandatory coverage categories (E-01), scans a draft spec and
marks each Clear / Partial / Missing, builds a prioritised and track-capped
question queue by Impact × Uncertainty, and routes each unresolved high-impact
dimension to a `[NEEDS CLARIFICATION]` marker or a `decision_to_confirm` while
recording every other dimension as an `## Assumptions` line.

What it is (and is NOT), mirroring `spec_review.py` / `spec_selfcheck.py`:
  * It PRODUCES the coverage map, the candidate-question queue (each question a
    real interrogative + a one-line why-it-matters + a recommended default), and
    the routed markers / decisions / assumption lines, plus a callable API.
  * It does NOT make an LLM call and it is NOT a rule engine — the discovery
    agent (via E-03 / KLC-090) decides which candidate questions to actually ask.
  * It does NOT wire itself into discovery.md / discovery-lite.md and invents no
    new human gate — the routed decisions flow to the EXISTING discovery/design
    ack decision gate that `spec_review.route_decisions` already feeds.

Single source of truth (C-001): the mandatory categories and their `min_track`
floors are resolved ONLY through `coverage_taxonomy.for_track` / `by_id`. The
engine never re-parses the taxonomy file and keeps no private copy of the
category list — a second parse is the exact drift single-source exists to
prevent (`coverage_taxonomy.py` is the one and only reader of that file).

Degrade-not-fail (C-002): an absent / malformed taxonomy, an empty draft spec,
or an unknown track yields an empty coverage map / empty queue / empty result —
never an exception out of a consumer-facing accessor. The engine surfaces; it
never blocks a phase by crashing it.
"""
from __future__ import annotations

import functools
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Package-safe path setup (mirrors spec_selfcheck.py / coverage_taxonomy.py):
# make both the project root and this skills dir importable so the bare
# `import coverage_taxonomy` / `import spec_saoc` / `import spec_review` resolve
# under BOTH a script run and a `core.skills.elicitation` package import.
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
for _p in (str(_project_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import coverage_taxonomy as _tax  # noqa: E402  (the ONE reader; never re-parse the YAML)
import spec_saoc as _saoc  # noqa: E402  (AC parsing for the functional-scope scan)


# --- classification status ---------------------------------------------------

CLEAR = "Clear"
PARTIAL = "Partial"
MISSING = "Missing"


@dataclass
class CategoryCoverage:
    """One coverage category classified against the draft spec."""

    id: str
    status: str  # one of CLEAR / PARTIAL / MISSING
    # Optional per-category evidence detail. For a Partial functional-scope it
    # carries {"missing_leg": "acceptance-criteria" | "boundary"} so the routed
    # recommendation is honest about WHICH leg is missing (FIX A).
    detail: dict = field(default_factory=dict)


# Per-category heading + content keywords. A dedicated section whose heading
# carries one of these keywords is strong evidence the category is covered; the
# same keywords appearing only in body prose is weaker (Partial) evidence. The
# category ids and floors themselves are NEVER hard-coded here — only this
# scan-vocabulary, which is the engine's own heuristic, not the taxonomy.
_KEYWORDS = {
    "functional-scope": ("goal", "scope", "behavior", "behaviour", "objective"),
    "domain-data-model": ("data", "entit", "domain", "schema", "attribute",
                          "relationship", "lifecycle"),
    "interaction-ux": ("interaction", "ux", "user flow", "flow", "ui",
                       "interface", "input", "output"),
    "nfr": ("non-functional", "nfr", "quality", "performance", "reliability",
            "security", "observab"),
    "integration-external": ("integration", "external", "dependen", "api",
                             "contract", "upstream", "downstream"),
    "edge-failure": ("edge", "failure", "boundary", "error", "recovery",
                     "rollback", "abuse"),
    "constraints-tradeoffs": ("constraint", "tradeoff", "trade-off", "assumption"),
    "terminology": ("terminology", "glossary", "definition", "term"),
    "completion-signals": ("completion", "done criteria", "done", "acceptance",
                           "success criteria"),
    "misc-placeholders": ("open question", "placeholder", "todo", "tbd",
                          "fixme", "miscellaneous"),
}

# Categories with INVERTED polarity (a per-category flag modelled as a set, not a
# scattered `if`, so the same inversion applies to any future negative-signal
# category). For a NORMAL category a keyword hit is EVIDENCE the dimension is
# covered. For an inverted one the hit is the loose end the category exists to
# CATCH — an open question / TODO / placeholder is the PROBLEM — so the classifier
# negates the evidence: a hit → UNRESOLVED (route it for cleanup), and the ABSENCE
# of any hit → Clear (the good state). Only misc-placeholders is inverted today;
# terminology is NOT (its sub_checks — defined-terms / consistent-naming / glossary
# — are positive signals: HAVING a glossary is coverage, not a defect).
_INVERTED_CATEGORIES = frozenset({"misc-placeholders"})

# The ACTUAL loose-end markers for misc-placeholders. Because this category is
# INVERTED, a hit means "unresolved", so a FALSE positive on clean prose is the
# costly direction (FIX B). The generic per-category keyword/sub_check tokenizer
# matched COMPONENT words of the compound sub_checks — `open`/`markers`/`questions`
# — so ordinary prose ("open the modal", a map's "markers") tripped it. Match the
# real markers as PHRASES / specific tokens instead: word-boundaried todo / tbd /
# fixme / xxx, the adjacent phrase "open question(s)", `placeholder(s)`, a
# `[NEEDS CLARIFICATION]` marker, and a bare `???`.
_LOOSE_END_RE = re.compile(
    r"\btodos?\b|\btbds?\b|\bfixmes?\b|\bxxx\b"
    r"|\bopen\s+questions?\b"
    r"|\bplaceholders?\b"
    r"|needs\s+clarification"
    r"|\?\?\?",
    re.IGNORECASE,
)

# Per-inverted-category dedicated evidence matcher (overrides the generic keyword/
# sub_check scan). A future inverted category registers its own precise matcher
# here rather than reusing the loose component-word tokenizer.
_INVERTED_EVIDENCE = {
    "misc-placeholders": _LOOSE_END_RE,
}

# Non-goals / out-of-scope / exclusion heading keywords — the boundary evidence
# (functional-scope's `out-of-scope` leg). `exclusion` (word-start) also matches
# `exclusions`; `excluded` covered separately (HARDENING 2, kept in lockstep with
# `_QUALIFIER` below so a boundary heading reads the same in both places).
_NONGOAL_KEYWORDS = ("non-goal", "non goals", "out-of-scope", "out of scope",
                     "not in scope", "exclusion", "excluded")

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$", re.MULTILINE)

# The GOAL-word vocabulary — a strict SUPERSET of the pre-round-3 tokens
# (goal(s)/objective(s)/scope/behavior/behaviour) plus purpose. Round-3 narrowed
# this by dropping behavior/behaviour, which spuriously blocked a spec whose scope
# lived under a `## Behavior` heading; keep every historical token here so a
# refactor cannot silently drop one again. `behaviou?r` covers both spellings.
_GOAL_WORD_ALT = r"(?:goals?|objectives?|purpose|scope|behaviou?rs?)"
# A standalone GOAL word (functional-scope's Goals-section evidence).
_GOAL_WORD_RE = re.compile(r"\b" + _GOAL_WORD_ALT + r"\b")

# A BOUNDARY qualifier, allowing a hyphen or a space between segments. Covers the
# non-goal / out-of-scope forms PLUS the exclusion forms (HARDENING 2): a
# `## Scope exclusions` / `## Exclusions from scope` heading is a boundary, not a
# goals section — the compound `scope exclusions` / `exclusions from scope` phrases
# are listed as whole qualifiers (BEFORE the bare `exclusions?`) so the goal word
# `scope` in them is consumed by the qualifier and never survives as goal evidence.
_QUALIFIER = (
    r"(?:"
    r"non[-\s]?goals?"
    r"|out[-\s]?of[-\s]?scope"
    r"|not\s+in\s+scope"
    r"|scope[-\s]?exclusions?"          # "scope exclusions" — a boundary, incl. its goal word
    r"|exclusions?\s+from\s+scope"      # "exclusions from scope" — likewise
    r"|exclusions?"
    r"|excluded"
    r")"
)
# The separator between a boundary qualifier and its goal word(s), and between
# goal words in the trailing list. It is ANY run of non-word characters (colon, em
# dash, comma, slash, space, ...) OR a spelled-out `and`/`or` connective — so the
# WHOLE punctuation class is consumed, not just hyphen/space (HARDENING 4). A pure
# `\W+` cannot span " and " (its letters are word chars), hence the explicit
# and/or branch, tried first so " and " is taken as one connective.
_SEP = r"(?:\s*(?:\band\b|\bor\b)\s*|\W+)"
# A qualifier DIRECTLY followed by a goal word (across ANY separator run) — the
# "Out-of-scope goals" / "Out-of-scope: goals" / "Non-goals — objectives" trap —
# AND then any trailing list of goal words, so a boundary qualifier scopes over the
# WHOLE conjunction/list and none survives as false goal evidence. The goal-word
# part MUST use the same vocabulary as the standalone check above. The whole match
# is ANCHORED at a qualifier, so the separator runs only apply AFTER a boundary
# qualifier — a genuine leading goals list (no qualifier) is never eaten.
_QUALIFIER_PLUS_GOAL_RE = re.compile(
    _QUALIFIER + r"\W+" + _GOAL_WORD_ALT + r"\b"
    + r"(?:" + _SEP + _GOAL_WORD_ALT + r"\b)*"
)
_QUALIFIER_RE = re.compile(_QUALIFIER)


def _names_goals(heading: str) -> bool:
    """True when a heading names GOALS as its own subject — robust in ONE pass.

    A boundary heading (Non-goals / out-of-scope) carries a goal word but is NOT a
    goals section (codex-P2); a COMBINED heading ("Goals and Non-goals") DOES name
    goals and must count (FIX B); and a boundary qualifier directly in front of a
    goal word ("Out-of-scope goals", "Non-goal objectives") is a PURE boundary
    heading whose goal word must NOT survive (FIX C — else the blocking
    clarification is suppressed while the core goal is actually missing).

    Algorithm: (1) lowercase; (2) delete every "<qualifier> <goal-word>" as a unit;
    (3) delete any remaining standalone qualifier; (4) goal-evidence iff a
    standalone goal word still survives.
    """
    h = heading.lower()
    h = _QUALIFIER_PLUS_GOAL_RE.sub(" ", h)   # (2) qualifier+goalword as a unit
    h = _QUALIFIER_RE.sub(" ", h)             # (3) remaining standalone qualifiers
    return bool(_GOAL_WORD_RE.search(h))      # (4) a surviving standalone goal word


def _has_real_ac(acs: list) -> bool:
    """True when at least one acceptance criterion carries NON-EMPTY body content.

    An empty `- [ ] AC-1:` stub is still returned by parse_acs as an AC object but
    evidences nothing, so a bare object count would falsely credit the success-
    criteria / done-criteria leg. Both the functional-scope success-criteria leg
    (HARDENING 3) and the completion-signals category (FIX A) gate on this."""
    return any((getattr(ac, "body", "") or "").strip() for ac in (acs or []))


def _functional_legs(headings: list[str], acs: list) -> tuple[bool, bool, bool]:
    """The three evidence legs for functional-scope: (a real goals section, real
    acceptance criteria, an explicit out-of-scope boundary)."""
    goals_heading = any(_names_goals(h) for h in headings)
    ac_present = _has_real_ac(acs)
    nongoals = any(_any_keyword(h, _NONGOAL_KEYWORDS) for h in headings)
    return goals_heading, ac_present, nongoals


def _headings(text: str) -> list[str]:
    return [m.group(1).strip().lower() for m in _HEADING_RE.finditer(text)]


@functools.lru_cache(maxsize=None)
def _kw_regex(kw: str) -> re.Pattern:
    """A compiled WORD-START-anchored matcher for a keyword / sub-check token.

    Anchoring at a leading word boundary (`\\b`) — rather than a raw substring —
    closes the short-token class where e.g. `ui` matched inside `build` and
    falsely marked interaction-ux covered (HARDENING 1). A trailing boundary is
    deliberately NOT required, so the tolerant prefix/inflection matching the scan
    relies on is preserved: `data` still matches `database`, `entit` matches
    `entities`, `dependen` matches `dependency`, `goal` matches `goals`. What is
    excluded is only a token embedded MID-word in an unrelated word.
    """
    return re.compile(r"\b" + re.escape(kw))


def _any_keyword(haystack: str, keywords: tuple[str, ...]) -> bool:
    return any(_kw_regex(k).search(haystack) for k in keywords)


def _sub_check_evidenced(text_low: str, slug: object) -> bool:
    """A sub_check slug is evidenced when any of its >=4-char word-parts appears
    in the spec body as a WHOLE-TOKEN match (word-start boundary, HARDENING 1) —
    so a part is not satisfied by being a substring of an unrelated word.
    Deliberately tolerant otherwise — a surfaced heuristic, never a hard gate."""
    if not isinstance(slug, str):
        return False
    parts = [w for w in slug.split("-") if len(w) >= 4]
    return any(_kw_regex(p).search(text_low) for p in parts)


def _classify(text: str, text_low: str, headings: list[str], cat: dict,
              acs: list) -> str:
    """Classify one category as CLEAR / PARTIAL / MISSING against the draft spec."""
    cat_id = cat.get("id")
    keywords = _KEYWORDS.get(cat_id, ())
    heading_hit = bool(keywords) and any(_any_keyword(h, keywords) for h in headings)
    content_hit = bool(keywords) and _any_keyword(text_low, keywords)
    # Normalize a non-list sub_checks (a malformed but loadable override could
    # carry a SCALAR here) to [] before iterating — a bare `or []` still lets a
    # truthy scalar (e.g. an int) through and raises TypeError, escaping the
    # degrade-not-fail contract (C-002).
    sub_checks = cat.get("sub_checks")
    sub_checks = sub_checks if isinstance(sub_checks, list) else []
    evidenced = sum(1 for s in sub_checks if _sub_check_evidenced(text_low, s))

    if cat_id == "functional-scope":
        # A real goals section (via _names_goals, which rejects a PURE Non-goals
        # heading but accepts a combined "Goals and Non-goals") is the load-bearing
        # evidence: without it the core goal/scope is unknown → Missing, even when
        # ACs or a Non-goals boundary exist. With it, Clear still needs the other
        # two legs (real ACs via spec_saoc + an explicit boundary); thinner → Partial.
        goals_heading, ac_present, nongoals = _functional_legs(headings, acs)
        if not goals_heading:
            return MISSING
        if ac_present and nongoals:
            return CLEAR
        return PARTIAL

    if cat_id == "completion-signals":
        # The done/acceptance leg is Clear only on REAL acceptance-criteria BODY
        # content — a bare `## Acceptance Criteria` heading or the mere words
        # "acceptance"/"criteria" must not clear it (FIX A). With real ACs → Clear;
        # a heading/mention but no content-bearing AC → Partial (surfaces the
        # criteria question); nothing at all → Missing.
        if _has_real_ac(acs):
            return CLEAR
        if heading_hit or content_hit:
            return PARTIAL
        return MISSING

    if cat_id in _INVERTED_CATEGORIES:
        # INVERTED polarity: a hit is the loose end the category exists to catch, so
        # ANY hit → UNRESOLVED (route it for cleanup) and ABSENCE → Clear (the good
        # state) — the exact inverse of the positive branch below. The evidence uses
        # a dedicated PRECISE matcher (FIX B) so a component word of a compound
        # sub_check does not false-positive on clean prose.
        matcher = _INVERTED_EVIDENCE.get(cat_id)
        if matcher is not None:
            found = bool(matcher.search(text_low))
        else:
            found = heading_hit or content_hit or evidenced > 0
        return MISSING if found else CLEAR

    if not heading_hit and not content_hit:
        return MISSING
    # A dedicated section AND a majority of sub_checks evidenced reads Clear;
    # anything thinner (a mention without a section, or a section with unevidenced
    # facets) reads Partial.
    if heading_hit and sub_checks and evidenced >= (len(sub_checks) + 1) // 2:
        return CLEAR
    if heading_hit and not sub_checks:
        return CLEAR
    return PARTIAL


def _strip_frontmatter(text: str) -> str:
    """Strip a leading YAML frontmatter block (metadata) so it is not scanned as
    spec-body content.

    Only a block at the VERY START counts: the first non-empty line must be `---`
    and there must be a later closing `---` line. Metadata such as
    `risk_tags: [security]` would otherwise be miscounted as NFR body content and
    wrongly mark `nfr` covered (the risk_tags SIGNAL comes from the `signals=`
    argument, not from parsing the text, so stripping loses no boost). A `---`
    thematic break MID-body — or a leading `---` with no closing fence — is NOT
    frontmatter and is left untouched.
    """
    if not text:
        return text
    lines = text.splitlines(keepends=True)
    if lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[i + 1:])
    return text  # no closing fence → not a frontmatter block; leave as-is


def scan_coverage(spec_text: str, track: str) -> list[CategoryCoverage]:
    """Classify each track-mandatory coverage category against *spec_text*.

    The mandatory categories are resolved ONLY through
    `coverage_taxonomy.for_track(track)` (single-source; `[]` for an unknown
    track or an absent taxonomy). An empty / whitespace-only spec degrades to an
    empty coverage map. Never raises.
    """
    if not spec_text or not spec_text.strip():
        return []
    # Normalize the track BEFORE the taxonomy lookup (codex-P2): a valid but
    # lowercase / padded track ("s", " S ") must resolve like its canonical form,
    # not be treated as unknown and silently skip ALL mandatory elicitation.
    track = (track or "").strip().upper()
    cats = _tax.for_track(track)  # single-source; [] if absent/unknown track
    if not cats:
        return []
    # Strip leading YAML frontmatter so metadata (risk_tags, track, ...) is not
    # miscounted as spec-body coverage evidence.
    body = _strip_frontmatter(spec_text)
    text_low = body.lower()
    headings = _headings(body)
    acs = _saoc.parse_acs(body)
    out: list[CategoryCoverage] = []
    for cat in cats:
        cat_id = cat.get("id")
        if not isinstance(cat_id, str):
            continue
        status = _classify(body, text_low, headings, cat, acs)
        cov = CategoryCoverage(id=cat_id, status=status)
        # Record which leg is missing for a Partial functional-scope, so the
        # routed recommendation is honest (a boundary default is wrong when the
        # actual gap is the acceptance criteria) — FIX A.
        if cat_id == "functional-scope" and status == PARTIAL:
            _, ac_present, _ = _functional_legs(headings, acs)
            cov.detail = {"missing_leg": "boundary" if ac_present else "acceptance-criteria"}
        out.append(cov)
    return out


# --- step-2: the prioritised + track-capped question queue ------------------

# Uncertainty from the Clear / Partial / Missing classification: a Clear category
# has zero Uncertainty, so its Impact × Uncertainty score is zero and it never
# queues (AC-3). Missing (2) outranks a same-Impact Partial (1) for free, because
# Impact × 2 > Impact × 1 — the ordering invariant falls straight out of the
# arithmetic, no special-case tiebreak needed.
_UNCERTAINTY = {CLEAR: 0, PARTIAL: 1, MISSING: 2}

# The per-track question cap (AC-4): at most three on S, at most five on M/L. XS
# rarely reaches here (its two mandatory categories are cheap), but carries a cap
# for completeness. An unknown track defaults to the M/L cap.
_CAP = {"XS": 1, "S": 3, "M": 5, "L": 5}

# min_track floor → rank; Impact is (4 - rank), so a LOWER floor (a more
# foundational category, mandatory even on a light track) scores a HIGHER base
# Impact (Q-002). Read via `coverage_taxonomy.by_id`, never a private floor copy.
_FLOOR_RANK = {"XS": 0, "S": 1, "M": 2, "L": 3}

# risk_tag → the categories it escalates (Q-002). An aligned tag lifts the
# category's Impact by one, so e.g. a `security` ticket pushes `nfr` up the queue.
_RISK_ALIGN = {
    "security": {"nfr"},
    "data": {"domain-data-model"},
    "user-facing": {"interaction-ux"},
    "migration": {"domain-data-model", "integration-external"},
    "coordination": {"integration-external"},
    "performance": {"nfr"},
}

# HOUSEKEEPING = genuine bookkeeping only: misc-placeholders interrogates leftover
# TODO / placeholder markers. It is XS-floor (mandatory even on a light track), but
# Impact derived purely from the floor would rank it ABOVE the S-floor substantive
# categories (domain / interaction / edge), so the question cap would keep "any
# leftover TODOs?" and drop "what are the core entities?" (LOW review finding). Pin
# its Impact low so the human-facing questions lead with substance.
#
# completion-signals is deliberately NOT here: in the coverage taxonomy it means
# the measurable Definition of Done / acceptance-criteria testability, which is
# SUBSTANTIVE. Demoting it once let a Goals-only spec (no ACs) pass without ever
# being asked for its success criteria; keeping it at its floor Impact surfaces
# that gap through this category (FIX A).
_HOUSEKEEPING = {"misc-placeholders"}


@dataclass
class Question:
    """One candidate elicitation question for an unresolved coverage category.

    Carries a real interrogative, a one-line why-it-matters, and a recommended
    default (all three mandatory, AC-5), plus the scoring inputs and the routing
    hints (`defensible_default`, `topic`) the router reads in step-3.
    """

    category_id: str
    interrogative: str
    why: str
    recommended: str
    impact: int
    uncertainty: int
    score: int
    defensible_default: bool = True
    topic: str = "scope"  # a spec_review.DECISION_TOPICS value


# Per-category question templates. Each supplies the interrogative + why-it-
# matters + a recommended default, whether that default is DEFENSIBLE (the step-3
# marker-vs-decision discriminator, Q-001), and the decision topic to use when it
# routes to a decision_to_confirm. `functional-scope` is the one category whose
# core goal/scope cannot be safely guessed — when it is Missing there is no
# defensible default, so it is the (rare) blocking path.
_TEMPLATES = {
    "functional-scope": {
        "interrogative": "What are the core user goals and what is explicitly out of scope?",
        "why": "Without a bounded goal and an explicit scope, no acceptance criterion can be judged complete or correct.",
        "recommended": "(no safe default — the core goal and scope must come from the requester)",
        "defensible": False,
        "topic": "scope",
    },
    "domain-data-model": {
        "interrogative": "What are the core entities, their identities, and their lifecycle states?",
        "why": "The data model shapes storage, validation, and every downstream flow.",
        "recommended": "Assume the entities named in the goals, each with a single stable id and no explicit lifecycle states.",
        "defensible": True,
        "topic": "scope",
    },
    "interaction-ux": {
        "interrogative": "What are the primary user flows and the error and empty states?",
        "why": "Unspecified flows and error states are where behaviour silently diverges from intent.",
        "recommended": "Assume one primary happy-path flow with standard error surfacing and no empty-state special-casing.",
        "defensible": True,
        "topic": "scope",
    },
    "nfr": {
        "interrogative": "What are the measurable quality targets (performance, security, reliability) and how are they observed?",
        "why": "Without measurable non-functional targets, quality is asserted rather than verified.",
        "recommended": "Assume no special performance or security target beyond the existing defaults, and no new observability.",
        "defensible": True,
        "topic": "tradeoff",
    },
    "integration-external": {
        "interrogative": "Which external services or data contracts does this depend on, and how do their failures degrade?",
        "why": "Unhandled dependency-failure modes are a common source of production incidents.",
        "recommended": "Assume no new external dependency; existing contracts and versions are unchanged.",
        "defensible": True,
        "topic": "scope",
    },
    "edge-failure": {
        "interrogative": "What are the boundary conditions, abuse cases, and recovery or rollback behaviour?",
        "why": "Edge and failure handling is where correctness under stress is decided.",
        "recommended": "Assume standard input validation, no adversarial threat model, and a fail-safe degrade on error.",
        "defensible": True,
        "topic": "tradeoff",
    },
    "constraints-tradeoffs": {
        "interrogative": "What technical or business constraints apply, and what tradeoffs are being made?",
        "why": "Unstated constraints and tradeoffs get discovered late, as rework.",
        "recommended": "Assume no constraint beyond the existing stack and only the tradeoffs already implied by the track.",
        "defensible": True,
        "topic": "tradeoff",
    },
    "terminology": {
        "interrogative": "Are the domain terms defined consistently, with a glossary where they are ambiguous?",
        "why": "Ambiguous terminology causes two readers to build two different things.",
        "recommended": "Assume terms carry their standard meaning in this codebase; no new glossary is needed.",
        "defensible": True,
        "topic": "ambiguous-intent",
    },
    "completion-signals": {
        "interrogative": "What are the done criteria and acceptance signals that say the work is finished?",
        "why": "Without explicit done criteria, completion is a matter of opinion.",
        "recommended": "Assume the acceptance criteria plus a green regression suite are the done signal.",
        "defensible": True,
        "topic": "scope",
    },
    "misc-placeholders": {
        "interrogative": "Are there open questions, TODOs, or unresolved placeholders left in the draft?",
        "why": "Unresolved placeholders are unfinished thinking that leaks into the build.",
        # Inverted category: it only ever surfaces when a loose end EXISTS, so the
        # recommendation is the cleanup action, not a (false) "nothing remains".
        "recommended": "Resolve or remove the open questions / TODO / placeholder markers before the spec is final.",
        "defensible": True,
        "topic": "ambiguous-intent",
    },
}


def _generic_template(cat_id: str) -> dict:
    """Fallback template for a category with no bespoke entry (e.g. a category the
    taxonomy adds later) — keeps the engine degrade-not-fail rather than raising."""
    label = (cat_id or "this dimension").replace("-", " ")
    return {
        "interrogative": f"Is the {label} dimension covered by the draft spec?",
        "why": f"The {label} dimension is mandatory at this track but currently unaddressed.",
        "recommended": f"Assume the default handling for {label}.",
        "defensible": True,
        "topic": "scope",
    }


def _floor_rank(min_track: object) -> int:
    """Rank of a `min_track` floor, guarding a NON-STRING floor (e.g. a list from
    a malformed override) so it is never used as a dict key — a raw lookup would
    raise `TypeError: unhashable type`. Mirrors `coverage_taxonomy._floor_rank`,
    keeping the public `_impact` / `build_question_queue` degrade-not-fail."""
    if not isinstance(min_track, str):
        return 3  # unknown / malformed floor → least foundational
    return _FLOOR_RANK.get(min_track, 3)


def _impact(cat_id: str, signals: dict | None = None) -> int:
    """Base Impact from the category's `min_track` floor (read single-source via
    `coverage_taxonomy.by_id`), escalated by one when an aligned risk_tag fires.

    Housekeeping categories are pinned to the lowest Impact so the capped question
    queue leads with substance rather than TODO/done-signal bookkeeping."""
    if cat_id in _HOUSEKEEPING:
        impact = 1
    else:
        cat = _tax.by_id(cat_id) or {}
        impact = 4 - _floor_rank(cat.get("min_track"))  # XS→4, S→3, M→2, L→1
    tags = (signals or {}).get("risk_tags") or []
    if any(cat_id in _RISK_ALIGN.get(t, ()) for t in tags):
        impact += 1
    return max(1, impact)


# The two honest defaults for a PARTIAL functional-scope, chosen by WHICH leg is
# missing (FIX A). A boundary default is only correct when the goal AND the ACs
# are present and merely the out-of-scope boundary is unstated; when the ACs are
# the missing leg, the honest recommendation asks for the success criteria and
# does NOT assert a scope boundary (that gap also surfaces via completion-signals).
_FUNCTIONAL_SCOPE_BOUNDARY_DEFAULT = (
    "Assume the scope described in the Goals section is complete and treat "
    "anything not listed there as explicitly out of scope."
)
_FUNCTIONAL_SCOPE_ACS_DEFAULT = (
    "Confirm the acceptance criteria / measurable success criteria for the stated "
    "goal before build — the goal is named but its success signals are not defined."
)


def _question_for(cov: CategoryCoverage, impact: int, uncertainty: int) -> Question:
    tpl = _TEMPLATES.get(cov.id) or _generic_template(cov.id)
    recommended = tpl["recommended"]
    defensible = tpl["defensible"]
    # functional-scope has NO defensible default ONLY when it is Missing — the
    # core goal cannot be guessed, so it BLOCKS. When it is Partial the goal is
    # present, so it HAS a defensible default and routes to a decision_to_confirm;
    # the recommendation is honest about which leg is missing (the boundary vs the
    # acceptance criteria) rather than always recommending a scope boundary.
    if cov.id == "functional-scope" and cov.status != MISSING:
        defensible = True
        if (cov.detail or {}).get("missing_leg") == "acceptance-criteria":
            recommended = _FUNCTIONAL_SCOPE_ACS_DEFAULT
        else:
            recommended = _FUNCTIONAL_SCOPE_BOUNDARY_DEFAULT
    return Question(
        category_id=cov.id,
        interrogative=tpl["interrogative"],
        why=tpl["why"],
        recommended=recommended,
        impact=impact,
        uncertainty=uncertainty,
        score=impact * uncertainty,
        defensible_default=defensible,
        topic=tpl["topic"],
    )


def build_question_queue(coverage: list[CategoryCoverage], track: str,
                         signals: dict | None = None) -> list[Question]:
    """Build the prioritised, track-capped candidate-question queue (AC-3/4/5).

    Score each non-Clear category by Impact × Uncertainty, drop the Clear ones
    (Uncertainty 0 → score 0), order by descending score (Missing outranks a
    same-Impact Partial for free), and truncate to the per-track cap. Degrade-
    not-fail: an empty / None coverage yields an empty queue.
    """
    scored: list[Question] = []
    for cov in coverage or []:
        uncertainty = _UNCERTAINTY.get(cov.status, 0)
        if uncertainty == 0:
            continue  # Clear (or unknown status) → never queues
        scored.append(_question_for(cov, _impact(cov.id, signals), uncertainty))
    # Highest score first; a stable secondary key on Uncertainty then Impact keeps
    # ordering deterministic when two categories tie on score.
    scored.sort(key=lambda q: (q.score, q.uncertainty, q.impact), reverse=True)
    cap = _CAP.get((track or "").strip().upper(), 5)
    return scored[:cap]


# --- step-3: routing (marker / decision_to_confirm / ## Assumptions) ---------

import spec_review  # noqa: E402  (reuse the KLC-084 decision shape + validator, single-source)

# The Impact × Uncertainty score at or above which a dimension is "high-impact"
# and escalates (to a marker or a decision_to_confirm) rather than becoming a
# silent assumption. Below it, the dimension is guessed-by-default and recorded
# as an ## Assumptions line (AC-6/AC-7). With Impact in 1..5 and Uncertainty in
# 1..2, a threshold of 4 escalates Missing categories at every floor and Partial
# categories at the two most-foundational floors, while leaving the long tail of
# low-Impact Partial dimensions as assumptions — keeping blocking + surfacing rare.
_HIGH_IMPACT = 4


@dataclass
class ElicitationResult:
    """The full engine output: the coverage map, the candidate-question queue, and
    the routed markers / decisions / assumption lines."""

    coverage: list[CategoryCoverage] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    decisions: list = field(default_factory=list)  # list[spec_review.DecisionToConfirm]
    assumptions: list[str] = field(default_factory=list)


def _topic_for(question: Question) -> str:
    """The decision topic, guarded to the KLC-084 vocabulary so a routed decision
    always validates (an out-of-vocabulary topic falls back to `scope`)."""
    if question.topic in spec_review.DECISION_TOPICS:
        return question.topic
    return "scope"


def _route_one(res: ElicitationResult, q: Question) -> None:
    """Route ONE question into exactly one of markers / decisions / assumptions."""
    if q.score >= _HIGH_IMPACT:
        if q.defensible_default and q.recommended.strip():
            res.decisions.append(spec_review.DecisionToConfirm(
                id=f"D-{q.category_id}",
                topic=_topic_for(q),
                question=q.interrogative,
                recommended=q.recommended,
                rationale=q.why,
                ref=q.category_id,
            ))
        else:
            # The category id is carried in the marker so a consumer (and E-05)
            # can map an unresolved marker back to its coverage dimension.
            res.markers.append(
                f"[NEEDS CLARIFICATION ({q.category_id}): {q.interrogative}]")
    else:
        res.assumptions.append(f"- {q.category_id}: {q.recommended}")


def route(questions: list[Question], coverage: list[CategoryCoverage],
          track: str, signals: dict | None = None) -> ElicitationResult:
    """Route every unresolved dimension to a marker / decision / assumption.

    TWO DISTINCT BUDGETS (the FIX for the cap-drops-dimensions defect):
      * the QUESTION cap (`build_question_queue`, ≤3 S / ≤5 M/L) bounds only how
        many questions are put to the HUMAN — it is a human-attention budget.
      * ROUTING/RECORDING here must cover EVERY unresolved (Partial/Missing)
        category, so nothing a category cut by the question cap silently vanishes
        (the epic's completeness-by-construction thesis; E-05 inherits this map).

    A category's ROUTING must NOT depend on whether it fit under the question cap:
    `signals` is threaded here so a cap-dropped category is synthesized at the SAME
    risk-boosted Impact that `build_question_queue` used, scoring identically
    whether or not it made the queue (else a risk-aligned Partial that got cut
    would silently fall to an assumption instead of reaching the ack as a decision).

    The marker-vs-decision discriminator (Q-001, confirmed with the human) is
    WHETHER A DEFENSIBLE RECOMMENDED DEFAULT EXISTS — not impact alone:
      * high-impact AND no defensible default → a BLOCKING `[NEEDS CLARIFICATION]`
        marker (a genuine unknown that changes correctness; kept rare).
      * high-impact AND a defensible default → a non-blocking
        `spec_review.DecisionToConfirm` carrying the mandatory recommended answer,
        routed to the EXISTING discovery/design ack decision gate (guess-by-default).
      * everything below the threshold → an `## Assumptions` line.
    Degrade-not-fail: empty / None inputs yield an empty result.
    """
    res = ElicitationResult(coverage=list(coverage or []),
                            questions=list(questions or []))
    queued = {q.category_id: q for q in res.questions}
    routed_ids: set[str] = set()
    # (1) Route EVERY unresolved category in the coverage map — not just the
    # capped queue. Prefer the already-scored queue Question where one exists;
    # synthesize one for a category the cap dropped, at the SAME risk-boosted
    # Impact (`signals` threaded) so its route doesn't hinge on making the cut.
    for cov in res.coverage:
        uncertainty = _UNCERTAINTY.get(cov.status, 0)
        if uncertainty == 0:
            continue  # Clear → nothing to route
        q = queued.get(cov.id) or _question_for(cov, _impact(cov.id, signals), uncertainty)
        _route_one(res, q)
        routed_ids.add(cov.id)
    # (2) Route any queued question whose category is absent from the coverage map
    # (a direct route() caller may pass questions without a coverage list).
    coverage_ids = {c.id for c in res.coverage}
    for q in res.questions:
        if q.category_id not in coverage_ids and q.category_id not in routed_ids:
            _route_one(res, q)
            routed_ids.add(q.category_id)
    return res


def elicit(spec_text: str, track: str, signals: dict | None = None) -> ElicitationResult:
    """The convenience the discovery wiring (E-03 / KLC-090) will call: scan the
    draft spec, build the prioritised + capped question queue, and route it.

    Degrade-not-fail across every leg — an empty spec, an absent taxonomy, or an
    unknown track yields an empty `ElicitationResult` with no exception raised.
    """
    coverage = scan_coverage(spec_text, track)
    questions = build_question_queue(coverage, track, signals)
    return route(questions, coverage, track, signals)


if __name__ == "__main__":  # pragma: no cover - CLI smoke
    import argparse
    import json

    ap = argparse.ArgumentParser(description="elicitation engine (E-02)")
    ap.add_argument("--file", required=True)
    ap.add_argument("--track", default="M")
    args = ap.parse_args()
    text = Path(args.file).read_text(encoding="utf-8")
    result = elicit(text, args.track)
    print(json.dumps({
        "coverage": [{"id": c.id, "status": c.status} for c in result.coverage],
        "questions": [
            {"category_id": q.category_id, "interrogative": q.interrogative,
             "score": q.score, "recommended": q.recommended}
            for q in result.questions
        ],
        "markers": result.markers,
        "decisions": [d.to_dict() for d in result.decisions],
        "assumptions": result.assumptions,
    }, indent=2, ensure_ascii=False))
