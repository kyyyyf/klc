#!/usr/bin/env python3
"""testplan_review.py — deterministic adversarial-coverage review of a test-plan (KLC-085).

The mandatory external code reviewer checks CODE against the spec "as written";
this shifts the same independent-review discipline one artifact LEFT, onto the
TEST-PLAN. Its job is COVERAGE DESIGN: does every acceptance criterion (AC) in
`spec.md` map to at least one planned test, and is the plan more than happy-path?

Split of labour (mirrors the KLC-083 gate ↔ KLC-084 reviewer split):
  * DETERMINISTIC here — the AC→test coverage map (uncovered ACs), a happy-path
    heuristic, and a gate/reject-AC-without-a-negative-test heuristic. Mechanical,
    surfaced, may false-positive; never a hard fail.
  * JUDGMENT — deferred to the prose reviewer agent (`core/agents/test-plan-reviewer.md`)
    — tautological/faked tests (a test that cannot fail / asserts a stub; the
    KLC-057 lesson), and the deeper "is this coverage adequate" call.
  * OUT OF SCOPE (both) — whether the tests are actually implemented / not-faked
    in CODE. That stays the code reviewer's job.

Reuse (single source of truth, no duplicate plumbing):
  * `spec_saoc` — the KLC-083 SAOC recogniser; the ONLY parser of the ACs this
    deterministic review is anchored on.
  * KLC-084's generic independent-artifact-review seam (`spec_review`) — the
    INDEPENDENT reviewer's machine-readable verdict is parsed / validated / routed
    / recorded by that module UNCHANGED. We only describe the test-plan flavour of
    the seam here as `TEST_PLAN_REVIEW` (a `spec_review.ReviewKind` carrying the
    test-plan reviewer prompt, artifact, output file, finding categories and
    decision topics) and re-export `consume` bound to it. There is no second
    parser, validator, or router — the schema-generic seam carries this vocabulary.

Two independent layers, deliberately kept apart:
  * DETERMINISTIC coverage analysis (this module's `review`/`coverage_map`/…) — the
    mechanical AC→test map + happy-path + gate/negative heuristics. This is 085's
    own value-add, the analogue of `spec_selfcheck` for test-plans. It uses its own
    lightweight `Report`/`Finding` and never touches the seam.
  * INDEPENDENT reviewer verdict — the `test-plan-reviewer` agent writes
    `test-plan-review.md`; `consume` (via the 084 seam) parses it, routes its
    `decisions_to_confirm[]` to the ack, and records its `findings[]`.

Degrade-not-fail (a constitution principle): absent spec ACs or an absent/empty
test-plan each yield a single degraded SURFACE note and the review never raises —
the acceptance-test-plan phase must not crash on it.

Track scaling (track = floor): XS skips the review entirely; S runs the LIGHT set
(the coverage map only — the cascade default); M/L run the FULL set (adds the
happy-path and negative/boundary heuristics). This mirrors `spec_selfcheck`.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Package-safe path setup (mirrors spec_selfcheck.py): make both the project root
# and this skills dir importable so bare `import spec_saoc` resolves under script
# AND package invocation.
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
for _p in (str(_project_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import spec_saoc as _saoc  # noqa: E402
import spec_review as _spec_review  # noqa: E402

# This reviewer never blocks — it SURFACES. A coverage judgment is low-noise only
# if it elevates rather than adjudicates (the KLC-084 findings/decisions split);
# uncovered ACs are already a phase-failure via the test-planner agent, so adding
# a second hard gate here is redundant and is explicitly forbidden by the epic.
SURFACE = "surface"

# Track dimension sets. LIGHT is the S floor (cascade default); FULL adds the
# heavier heuristics for M/L. XS resolves to the empty set (skip).
_LIGHT = {"coverage"}
_HEAVY = {"happy_path", "negative_boundary"}

# The test-plan flavour of KLC-084's generic independent-artifact-review seam.
# This is a `spec_review.ReviewKind` descriptor: the ONLY things that differ from
# SPEC_REVIEW are the reviewer prompt, the artifact under review, the file the
# reviewer writes its verdict to, and — crucially — the OBJECTIVE finding
# categories and SUBJECTIVE decision topics. Because the category/topic vocabulary
# lives on the kind (not module-global in spec_review), `spec_review.validate`,
# `route_decisions`, `summarize_findings`, `record_findings` and `consume` all
# carry this test-plan vocabulary through UNCHANGED — no forked parser/validator.
#
#   finding_categories (OBJECTIVE — the reviewer decides, the implementer assesses):
#     uncovered-ac       an AC maps to no real planned test
#     weak-assertion     a planned test cannot fail as designed (tautological/faked
#                        assertion — the KLC-057 lesson, at the plan level)
#     missing-edge-case  a happy-path-only plan / a gate-or-reject AC with no
#                        negative / boundary / degrade case
#   decision_topics (SUBJECTIVE — elevated to the human at the ack decision gate):
#     coverage-depth       how much coverage is "enough" for this AC/risk
#     risk-prioritization  which risks the plan should prove first
TEST_PLAN_REVIEW = _spec_review.ReviewKind(
    name="test-plan",
    reviewer_prompt="core/agents/test-plan-reviewer.md",
    artifact="test-plan.md",
    output_file="test-plan-review.md",
    finding_categories=("uncovered-ac", "weak-assertion", "missing-edge-case"),
    decision_topics=("coverage-depth", "risk-prioritization"),
)

# Negative / edge / failure signal words. Matched PER coverage row and PER edge-case
# bullet (never over the whole plan text — the mandated `## Edge cases` heading itself
# contains "edge", which would make a plan-wide scan permanently true; see
# `_check_happy_path`). Deliberately broad and surfaced, never a hard fail.
_NEGATIVE_TOKENS = (
    "reject", "deny", "denied", "block", "invalid", "missing", "absent", "fail",
    "failure", "error", "degrade", "degraded", "boundary", "empty", "malformed",
    "unavailable", "negative", "edge", "timeout", "duplicate", "overflow",
    "underflow", "corrupt", "crash", "raises", "exception", "not found",
    "out of range", "conflict", "race", "null", "none", "zero", "unauthor",
    "forbidden", "refuse", "refused",
)

# Action words that make an AC a gate/validator/reject criterion — it MUST have a
# negative test (the gate bites on bad input), per the test-planner's discipline.
_GATE_ACTIONS = (
    "reject", "rejects", "deny", "denies", "block", "blocks", "refuse", "refuses",
    "validate", "validates", "forbid", "forbids", "prohibit", "prohibits",
    "disallow", "disallows", "fail", "fails", "degrade", "degrades",
    "guard", "guards", "enforce", "enforces",
)

# Placeholder cells that do NOT count as a real planned test location.
_PLACEHOLDER_CELLS = {"", "-", "—", "–", "tbd", "todo", "n/a", "na", "none", "..."}

_AC_ID_RE = re.compile(r"AC-\d+")


@dataclass
class Finding:
    dimension: str
    severity: str
    message: str
    ref: str = ""


@dataclass
class Report:
    track: str
    findings: list[Finding] = field(default_factory=list)
    coverage_map: dict[str, list[str]] = field(default_factory=dict)  # AC id → test refs
    degraded: bool = False

    @property
    def surfaced(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SURFACE]

    @property
    def ok(self) -> bool:
        # This reviewer never blocks; ok reflects "no surfaced coverage issue".
        return not self.surfaced


# --- test-plan parsing ------------------------------------------------------

def _section_body(text: str, heading_words: tuple[str, ...]) -> str:
    """Body under the first `## <heading>` matching *heading_words*, to the next
    level-2 heading. Empty string if the heading is absent."""
    body: list[str] = []
    capturing = False
    for line in text.splitlines():
        if re.match(r"^##\s+", line):
            if capturing:
                break
            head = line.lstrip("#").strip().lower()
            capturing = any(head.startswith(w) for w in heading_words)
            continue
        if capturing:
            body.append(line)
    return "\n".join(body)


@dataclass
class CoverageRow:
    ac_ids: list[str]     # AC ids named in the row (first cell + any covered-by note)
    test_type: str
    test_location: str
    has_real_test: bool   # the location cell names a genuine test (not a placeholder)
    negative: bool        # the row carries a negative/edge/failure signal
    raw: str


def parse_coverage_rows(test_plan_text: str) -> list[CoverageRow]:
    """Parse the `## Acceptance coverage` markdown table into rows.

    A row's ACs come from its dedicated AC column ONLY, plus any explicit
    `covered-by: AC-n` marker in another cell — NEVER from free-text in the Notes
    column. That distinction matters: a Notes line that merely mentions another AC
    ("does not cover AC-2") must not fake coverage for it, or a genuinely uncovered
    AC would escape the uncovered-ac advisory (KLC-085 review FIX-2). ``has_real_test``
    is True only when the test-name/location cell names a genuine test — a placeholder
    (`—`, `TBD`, empty) does NOT count as coverage, which is exactly the "AC listed
    but no test" hole this review must catch.
    """
    body = _section_body(test_plan_text, ("acceptance coverage", "acceptance"))
    rows: list[CoverageRow] = []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            continue
        # Skip the |---|---| separator row.
        if set("".join(cells)) <= set("-: ") and "-" in "".join(cells):
            continue
        # Skip the header row (first cell is literally the AC column label).
        if cells[0].lower() in ("ac", "ac-n"):
            continue
        # Covered AC ids come ONLY from the dedicated AC column, plus any explicit
        # `covered-by: AC-n` marker in a later cell. NOT from Notes/free-text, so a
        # Notes mention of another AC cannot fake coverage (FIX-2).
        ac_ids: list[str] = list(_AC_ID_RE.findall(cells[0]))
        for cell in cells[1:]:
            m = re.search(r"covered-by\s*:\s*([^|]*)", cell, re.IGNORECASE)
            if m:
                ac_ids += _AC_ID_RE.findall(m.group(1))
        # De-duplicate, preserving order (a row may name the same AC twice).
        ac_ids = list(dict.fromkeys(ac_ids))
        if not ac_ids:
            continue
        test_type = cells[1] if len(cells) > 1 else ""
        location = cells[2] if len(cells) > 2 else ""
        loc_norm = location.lower().strip()
        has_real = bool(loc_norm) and loc_norm not in _PLACEHOLDER_CELLS
        negative = _has_negative_signal(s)
        rows.append(CoverageRow(
            ac_ids=ac_ids, test_type=test_type, test_location=location,
            has_real_test=has_real, negative=negative, raw=s,
        ))
    return rows


def _has_negative_signal(text: str) -> bool:
    low = text.lower()
    return any(tok in low for tok in _NEGATIVE_TOKENS)


# --- the coverage map (AC-1) ------------------------------------------------

def coverage_map(spec_text: str, test_plan_text: str) -> dict[str, list[str]]:
    """Map each spec SAOC AC id to the planned tests that cover it.

    An AC maps to a test row iff the row names that AC AND has a real (non-
    placeholder) test location. The value is the list of test-location refs; an
    empty list means UNCOVERED.
    """
    ac_ids = [ac.id for ac in _saoc.parse_acs(spec_text)]
    rows = parse_coverage_rows(test_plan_text)
    mapping: dict[str, list[str]] = {ac_id: [] for ac_id in ac_ids}
    for row in rows:
        if not row.has_real_test:
            continue
        for ac_id in row.ac_ids:
            if ac_id in mapping:
                mapping[ac_id].append(row.test_location or row.test_type or row.raw)
    return mapping


# --- individual dimensions --------------------------------------------------

def _check_coverage(spec_text: str, test_plan_text: str, report: Report) -> list[Finding]:
    """AC→test coverage (LIGHT). Every spec AC must map to ≥1 real planned test."""
    mapping = coverage_map(spec_text, test_plan_text)
    report.coverage_map = mapping
    return [
        Finding("coverage", SURFACE,
                f"{ac_id} has no planned test in the acceptance-coverage table "
                f"(uncovered acceptance criterion)", ref=ac_id)
        for ac_id, tests in mapping.items() if not tests
    ]


def _check_happy_path(spec_text: str, test_plan_text: str) -> list[Finding]:
    """Happy-path-only heuristic (HEAVY).

    A plan with ACs is happy-path-only when it carries NO negative/failure/boundary
    signal in EITHER place a real test is planned:
      * no coverage ROW with a REAL test location carries a negative signal
        (`CoverageRow.negative and CoverageRow.has_real_test`) — a row that merely
        mentions a negative case but whose test location is a placeholder (`—`/`TBD`)
        is NOT evidence of a real negative test, so it must not suppress this check
        (KLC-085 review FIX-3 follow-on), AND
      * no meaningful `## Edge cases` BULLET names a negative/boundary token.

    We deliberately do NOT scan the whole plan text for a negative token here: the
    acceptance-test-plan phase MANDATES a `## Edge cases` heading (enforced upstream
    in phase_completion before this gate runs), and that heading contains the token
    "edge", so a plan-wide scan would be permanently True and this check would never
    fire on a filled-but-all-happy plan (KLC-085 review FIX-3). Warn-only; never blocks.
    """
    if not _saoc.parse_acs(spec_text):
        return []
    row_has_negative = any(
        r.negative and r.has_real_test for r in parse_coverage_rows(test_plan_text)
    )
    edge_body = _section_body(test_plan_text, ("edge cases", "edge"))
    edge_bullets = [
        item for line in edge_body.splitlines()
        if (item := line.strip().lstrip("-* ").strip())
        and item.lower() not in _PLACEHOLDER_CELLS
    ]
    edge_has_negative = any(_has_negative_signal(b) for b in edge_bullets)
    if row_has_negative or edge_has_negative:
        return []  # the plan proves at least one edge/failure/boundary case
    reasons = ["no coverage row carries a negative/failure/boundary test"]
    if not edge_bullets:
        reasons.append("the '## Edge cases' section is empty or a placeholder")
    else:
        reasons.append("the '## Edge cases' section names no negative/boundary case")
    return [Finding("happy_path", SURFACE,
                    "test-plan looks happy-path-only: " + "; ".join(reasons))]


def _check_negative_boundary(spec_text: str, test_plan_text: str) -> list[Finding]:
    """Gate/reject ACs without a negative test (HEAVY).

    A gate/validator/reject AC must have a test row that carries a negative/edge
    signal (the gate bites on bad input). One that maps only to happy-path rows is
    surfaced per-AC — the KLC-057 lesson that a gate needs a test that can fail.
    """
    rows = parse_coverage_rows(test_plan_text)
    out: list[Finding] = []
    for ac in _saoc.parse_acs(spec_text):
        if not ac.is_wellformed:
            continue
        action_words = set(re.findall(r"[a-z]+", ac.action.lower()))
        if not (action_words & set(_GATE_ACTIONS)):
            continue
        ac_rows = [r for r in rows if ac.id in r.ac_ids and r.has_real_test]
        if ac_rows and not any(r.negative for r in ac_rows):
            out.append(Finding(
                "negative_boundary", SURFACE,
                f"{ac.id} is a gate/reject criterion but its planned test(s) show "
                f"no negative/failure case — plan a test that bites on bad input",
                ref=ac.id))
    return out


# --- top-level review -------------------------------------------------------

def _active_dimensions(track: str) -> set[str]:
    t = (track or "").strip().upper()
    if t == "XS":
        return set()
    if t == "S":
        return set(_LIGHT)
    return set(_LIGHT | _HEAVY)  # M / L / unknown → full (fail-toward-more-review)


def review(spec_text: str, test_plan_text: str, track: str | None = None) -> Report:
    """Run the deterministic adversarial-coverage review for *track*.

    Degrade-not-fail: absent ACs or an absent/empty test-plan yields a single
    degraded SURFACE note and no dimension crashes the phase.
    """
    report = Report(track=(track or "").strip().upper() or "?")
    active = _active_dimensions(report.track)
    if not active:
        return report  # XS: skip entirely

    acs = _saoc.parse_acs(spec_text or "")
    if not acs:
        report.degraded = True
        report.findings.append(Finding(
            "coverage", SURFACE,
            "no SAOC acceptance criteria found in spec.md — coverage review degraded "
            "(nothing to anchor the test-plan against)"))
        return report
    if not (test_plan_text or "").strip():
        report.degraded = True
        report.findings.append(Finding(
            "coverage", SURFACE,
            "test-plan is absent or empty — coverage review degraded"))
        return report

    if "coverage" in active:
        report.findings += _check_coverage(spec_text, test_plan_text, report)
    if "happy_path" in active:
        report.findings += _check_happy_path(spec_text, test_plan_text)
    if "negative_boundary" in active:
        report.findings += _check_negative_boundary(spec_text, test_plan_text)
    return report


def warn_lines(report: Report) -> list[str]:
    """Compact one-line-per-finding advisories for the ack path (phase_completion)."""
    return [f"testplan-review[{f.dimension}]: {f.message}" for f in report.surfaced]


# --- the independent reviewer verdict: reuse KLC-084's seam, no fork ----------

def consume(ticket_dir, track, signals=None, persist: bool = True):
    """Consume the independent `test-plan-reviewer` verdict for this ticket.

    Thin binding of KLC-084's generic seam to `TEST_PLAN_REVIEW`: it delegates
    straight to `spec_review.consume` so the test-plan review reuses the SAME
    parser, validator, decision-router, findings-summariser and findings-recorder
    that the spec review uses — the schema-generic seam carries the test-plan
    finding categories / decision topics off `TEST_PLAN_REVIEW`. Returns
    `(advisories, findings)`; degrade-not-fail lives inside `spec_review.consume`.
    `persist=False` (a read-only probe: `klc remind` / gate-policy) surfaces the
    advisories WITHOUT writing `test-plan-review-findings.json`.
    """
    return _spec_review.consume(
        ticket_dir, track, signals, kind=TEST_PLAN_REVIEW, persist=persist
    )


# --- ticket-level entrypoint (used by phase_completion) ---------------------

def _ticket_dir(ticket: str) -> Path:
    try:
        from core.shared.paths import klc_ticket_meta_file
        return klc_ticket_meta_file(ticket).parent
    except Exception:
        return _project_root / ".klc" / "tickets" / ticket


def _read_track(ticket: str) -> str:
    # READ-ONLY: this only looks up the track, so it must use the non-migrating
    # reader. `read_meta`'s default write-back would let a persist=False probe
    # (`klc remind` / gate-policy, which reaches here via `run` → the coverage
    # gate) silently migrate a legacy phase string and dirty meta.json (KLC-062).
    try:
        import lifecycle as _lc
        return (_lc.read_meta_ro(ticket) or {}).get("track", "") or ""
    except Exception:
        return ""


def run(ticket: str, track: str | None = None) -> Report:
    """Load spec.md + test-plan.md for *ticket* and run the coverage review.

    Degrade-safe: a read error yields a degraded report, never an exception, so
    the acceptance-test-plan phase is never crashed by this check.
    """
    if track is None:
        track = _read_track(ticket)
    ticket_dir = _ticket_dir(ticket)
    try:
        spec_text = (ticket_dir / "spec.md").read_text(encoding="utf-8")
    except OSError:
        spec_text = ""
    try:
        test_plan_text = (ticket_dir / "test-plan.md").read_text(encoding="utf-8")
    except OSError:
        test_plan_text = ""
    try:
        return review(spec_text, test_plan_text, track)
    except Exception as exc:  # defensive: a surprise never fails the phase
        rep = Report(track=(track or "?").upper(), degraded=True)
        rep.findings.append(Finding("coverage", SURFACE,
                                    f"coverage review degraded ({exc!r})"))
        return rep


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="adversarial test-plan coverage review")
    ap.add_argument("--ticket")
    ap.add_argument("--spec")
    ap.add_argument("--test-plan")
    ap.add_argument("--track", default="M")
    args = ap.parse_args()

    if args.ticket:
        rep = run(args.ticket, args.track)
    else:
        spec_text = Path(args.spec).read_text(encoding="utf-8") if args.spec else ""
        tp_text = Path(args.test_plan).read_text(encoding="utf-8") if args.test_plan else ""
        rep = review(spec_text, tp_text, args.track)

    print(json.dumps({
        "track": rep.track,
        "ok": rep.ok,
        "degraded": rep.degraded,
        "coverage_map": rep.coverage_map,
        "surfaced": [f.__dict__ for f in rep.surfaced],
    }, indent=2, ensure_ascii=False))
    raise SystemExit(0)
