#!/usr/bin/env python3
"""spec_review.py — plumbing for an INDEPENDENT artifact review (KLC-084).

This is the generic seam that shifts the mandatory-external-reviewer discipline
LEFT onto a planning artifact. KLC-084 uses it for `spec.md`; KLC-085 reuses the
SAME module for `test-plan.md` with a different `ReviewKind` descriptor — the only
things that vary are the reviewer prompt, the artifact under review, and the file
the reviewer writes its verdict to.

What it does (and, deliberately, what it does NOT):
  * It CONSUMES a reviewer's machine-readable TWO-OUTPUT block and validates it.
  * It ROUTES `decisions_to_confirm[]` to the EXISTING discovery/design decision
    gate — i.e. it emits advisory lines in the exact shape `spec_selfcheck.warn_lines`
    uses, which `phase_completion` already surfaces at the human ack (a
    `decision`-level gate). No new human gate is invented.
  * It RECORDS `findings[]` for the implementer to assess (mirrors the mandatory
    code-reviewer flow: findings are assessed, not auto-applied).
  * It decides the review MODE by track (full / cascade / skip) per the epic
    matrix, reusing the review_cascade signal precedent.

What it is NOT: it does not make an LLM call and it is not a rule engine. The
actual spawn of the reviewer is orchestrator/autorunner-driven (like the code
reviewer); this module is the prompt-path + schema + routing seam around it.

The two output classes (see core/agents/spec-reviewer.md and KLC-082 epic):
  findings[]             OBJECTIVE, the reviewer decides -> to be fixed:
                         infidelity to raw.md, contradiction with current code,
                         constitution violation, untestable/ambiguous AC,
                         internal contradiction.
  decisions_to_confirm[] SUBJECTIVE, the HUMAN decides -> routed to the ack
                         decision gate: scope boundaries, tradeoffs, ambiguous
                         intent. Each carries a RECOMMENDED answer ("lead with a
                         recommendation"); validation ENFORCES that.

Degrade-not-fail (itself a constitution principle): a missing / malformed /
absent reviewer output NEVER raises out of the consume path — it degrades to a
single surfaced note, and the phase still completes.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import findings as _findings  # noqa: E402

# --- schema vocabularies ----------------------------------------------------

# The five OBJECTIVE finding classes the reviewer adjudicates (epic KLC-082).
FINDING_CATEGORIES = (
    "infidelity",            # spec drifts from raw.md intent
    "code-contradiction",    # a named verb/module doesn't exist, or the approach
                             # contradicts how the current code works
    "constitution",          # violates a constitution principle
    "untestable-ac",         # ambiguous / non-observable acceptance criterion
    "internal-contradiction",# two parts of the spec disagree
)

# The three SUBJECTIVE decision topics elevated to the human.
DECISION_TOPICS = ("scope", "tradeoff", "ambiguous-intent")

# Risk tags that, on an S ticket, ESCALATE a cascade review to a full review
# (mirrors review_cascade + the coordination-fuzz-gate precedent).
_ESCALATING_RISK_TAGS = frozenset(
    {"user-facing", "data", "security", "migration", "coordination"}
)


# --- the generic seam: a ReviewKind descriptor ------------------------------

@dataclass(frozen=True)
class ReviewKind:
    """One independent-artifact-review configuration — the generic seam.

    KLC-084 ships SPEC_REVIEW. KLC-085 adds a TEST_PLAN_REVIEW with a different
    prompt / artifact / output_file — AND its OWN finding categories — and reuses
    every function below unchanged. The category vocabulary lives on the kind (not
    module-global) precisely so `validate()` accepts the test-plan reviewer's
    classes (uncovered-ac, weak-assertion, missing-edge-case, …) without a second
    validator, and the advisory label uses `kind.name` rather than a hard-coded
    "spec-review" prefix.
    """
    name: str            # short label + advisory-label prefix, e.g. "spec"
    reviewer_prompt: str  # repo-relative path to the reviewer agent prompt
    artifact: str        # the artifact under review, e.g. "spec.md"
    output_file: str     # where the reviewer writes its verdict, e.g. "spec-review.md"
    finding_categories: tuple[str, ...] = FINDING_CATEGORIES   # OBJECTIVE classes
    decision_topics: tuple[str, ...] = DECISION_TOPICS         # SUBJECTIVE topics


SPEC_REVIEW = ReviewKind(
    name="spec",
    reviewer_prompt="core/agents/spec-reviewer.md",
    artifact="spec.md",
    output_file="spec-review.md",
    finding_categories=FINDING_CATEGORIES,
    decision_topics=DECISION_TOPICS,
)


# --- the two output classes -------------------------------------------------
#
# KLC-127: the OBJECTIVE finding is the one shape everywhere now —
# `findings.Finding` (rule_name, severity, file, line, title, body, fix,
# reviewer, id, kind, ref, ac). The old `spec_review.Finding` (id, category,
# severity, detail, ref, suggested_fix) is gone; `ReviewOutput.raw_findings`
# carries every raw finding dict (valid or not, for the D-106 old-shape/
# invalid-block detection) and `ReviewOutput.findings` carries only the
# entries that pass `findings.check_findings`, built via `findings.Finding`.

SEVERITIES = _findings.SEVERITIES        # KLC-127: the one severity vocabulary


@dataclass
class DecisionToConfirm:
    """A SUBJECTIVE call the reviewer NEVER adjudicates; it elevates it to the human."""
    id: str
    topic: str
    question: str
    recommended: str          # the "lead with a recommendation" answer (REQUIRED)
    rationale: str = ""
    ref: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReviewOutput:
    findings: list = field(default_factory=list)          # findings.Finding, VALID entries only
    raw_findings: list = field(default_factory=list)       # every raw finding dict, valid or not
    decisions_to_confirm: list[DecisionToConfirm] = field(default_factory=list)
    degraded: bool = False
    degrade_reason: str = ""


# --- parsing ----------------------------------------------------------------

# Grab ```json fenced blocks (the reviewer emits its verdict last, after any
# narrative); the LAST valid one wins. Fall back to a bare top-level object.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)


def _extract_json(text: str) -> dict | None:
    candidates = list(_JSON_FENCE_RE.findall(text))
    if not candidates:
        # Unfenced fallback: the whole text is a single {...} object.
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            candidates = [stripped]
    for raw in reversed(candidates):
        try:
            doc = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(doc, dict):
            return doc
    return None


def decisions_from_raw(raw) -> list[DecisionToConfirm]:
    """Build `DecisionToConfirm` records from a raw `decisions_to_confirm` list.

    Pure refactor (KLC-127): the loop `parse_review` used to run inline, now
    shared with `handback.validate_handback` so both paths build the exact
    same decision records from the exact same raw JSON.
    """
    return [DecisionToConfirm(id=str(d.get("id") or f"D-{i}"), topic=str(d.get("topic", "")),
                              question=str(d.get("question", "")),
                              recommended=str(d.get("recommended", "")),
                              rationale=str(d.get("rationale", "")), ref=str(d.get("ref", "")))
            for i, d in enumerate(raw, start=1) if isinstance(d, dict)]


def parse_review(text: str | None, kind: ReviewKind = SPEC_REVIEW) -> ReviewOutput:
    """Parse a reviewer's output text into a ReviewOutput.

    Degrade-not-fail: absent / empty / unparseable / schema-shaped-wrong input
    yields a ReviewOutput with degraded=True and a reason, never an exception.

    KLC-127: every raw finding dict is kept on `raw_findings` (valid or not —
    an old-shape or otherwise invalid entry is still visible there, for D-106's
    "leave the existing file untouched" detection); only the entries that pass
    `findings.check_findings` for *kind* become `findings.Finding` records on
    `out.findings`, stamped with `reviewer`/`kind` = `kind.name`.
    """
    if not text or not text.strip():
        return ReviewOutput(degraded=True, degrade_reason="no reviewer output")
    doc = _extract_json(text)
    if doc is None:
        return ReviewOutput(degraded=True, degrade_reason="no parseable JSON verdict block")

    # A valid-JSON-but-wrong-shape block (e.g. an orchestrator completion signal
    # `{"phase":...,"signal":"done"}` grabbed by last-block-wins) must NOT read as
    # a clean, issue-free verdict. A real verdict carries at least one of the two
    # output keys; a block with neither is not a verdict at all -> degrade.
    if "findings" not in doc and "decisions_to_confirm" not in doc:
        return ReviewOutput(
            degraded=True,
            degrade_reason="verdict block has neither findings nor decisions_to_confirm",
        )

    raw = [f for f in (doc.get("findings") or []) if isinstance(f, dict)]
    out = ReviewOutput(raw_findings=raw,
                       decisions_to_confirm=decisions_from_raw(doc.get("decisions_to_confirm") or []))
    for rec in raw:
        if not _findings.check_findings([rec], rule_names=kind.finding_categories, kind=kind.name):
            out.findings.append(_findings.Finding.from_dict(
                {**rec, "reviewer": kind.name, "kind": kind.name}))
    return out


# --- validation -------------------------------------------------------------

def _decision_errors(decisions: list[DecisionToConfirm], kind: ReviewKind,
                     finding_ids: set) -> list[str]:
    """The decision-half of `validate` — factored out so `handback.validate_handback`
    can reuse it against a hand-back's raw `decisions_to_confirm` (KLC-127)."""
    errors: list[str] = []
    seen_ids: set = set(finding_ids)
    for d in decisions:
        if d.id in seen_ids:
            errors.append(f"duplicate id {d.id!r}")
        seen_ids.add(d.id)
        if d.topic not in kind.decision_topics:
            errors.append(f"decision {d.id}: unknown topic {d.topic!r}")
        if not d.question.strip():
            errors.append(f"decision {d.id}: empty question")
        # The "lead with a recommendation" rule is MANDATORY, not optional.
        if not d.recommended.strip():
            errors.append(f"decision {d.id}: missing recommended answer")
    return errors


def validate(output: ReviewOutput, kind: ReviewKind = SPEC_REVIEW) -> list[str]:
    """Return a list of schema-conformance errors (empty == valid).

    Categories and topics are read FROM the active *kind*, so a KLC-085
    TEST_PLAN_REVIEW carrying its own classes validates through this same function
    (no per-kind validator). A degraded output has nothing to validate (its
    degradation is surfaced elsewhere), so it yields no errors here.

    KLC-127: the finding half now runs `findings.check_findings` over
    `output.raw_findings` (the one Finding shape, shared with `handback.py`).
    """
    if output.degraded:
        return []
    errors = _findings.check_findings(output.raw_findings,
                                      rule_names=kind.finding_categories, kind=kind.name)
    finding_ids = {r.get("id") for r in output.raw_findings if isinstance(r, dict)}
    return errors + _decision_errors(output.decisions_to_confirm, kind, finding_ids)


# --- routing decisions_to_confirm to the EXISTING ack decision gate ---------

def route_decisions(output: ReviewOutput, kind: ReviewKind = SPEC_REVIEW) -> list[str]:
    """Advisory lines for the discovery/design ack — the human decision gate.

    Returned in the shape `spec_selfcheck.warn_lines` uses, so `phase_completion`
    surfaces them at the same `decision`-level ack where the operator already
    signs off the spec. Each line LEADS WITH the reviewer's recommended answer,
    because the reviewer elevates the call — it never adjudicates it. The label
    prefix uses `kind.name`, so a KLC-085 test-plan review reads
    `test-plan-review[...]`. No new gate is introduced; the existing ack IS the gate.
    """
    if output.degraded:
        return [f"{kind.name}-review: reviewer output degraded ({output.degrade_reason}); "
                f"decisions_to_confirm unavailable"]
    lines: list[str] = []
    for d in output.decisions_to_confirm:
        rec = d.recommended.strip() or "(no recommendation given)"
        lines.append(
            f"{kind.name}-review[decision {d.id}/{d.topic}]: {d.question} "
            f"— RECOMMENDED: {rec}"
        )
    return lines


def summarize_findings(output: ReviewOutput, kind: ReviewKind = SPEC_REVIEW) -> list[str]:
    """A collapsed one-line summary of the OBJECTIVE findings for the ack.

    The findings are the reviewer's PRIMARY output ("correctly built the wrong
    thing"). This surfaces their existence + severity at the ack — mirroring how
    `spec_selfcheck.warn_lines` collapses its constitution checklist to a count —
    so the operator knows to have the implementer assess them at build. Empty when
    there are no findings; silent on a degraded output (route_decisions carries
    the degrade note, so it is not repeated here).
    """
    if output.degraded or not output.findings:
        return []
    highs = sum(1 for f in output.findings if f.severity.upper() in ("HIGH", "CRITICAL"))
    return [
        f"{kind.name}-review: {len(output.findings)} finding(s) recorded "
        f"({highs} high) in findings.json — assess before build"
    ]


# --- recording findings for the implementer ---------------------------------

def record_findings(output: ReviewOutput, ticket_dir: Path | None = None,
                    kind: ReviewKind = SPEC_REVIEW) -> list[dict]:
    """Return the findings as dicts for the implementer to assess.

    When *ticket_dir* is given, also persist them to
    `<ticket_dir>/findings.json` (kind `<name>-review`, round 1) so the build phase can read
    them (mirrors how the code-reviewer's findings are assessed, not auto-applied).
    Degrade-safe: a write failure or a degraded output never raises.
    """
    records = [f.to_dict() for f in output.findings]
    if ticket_dir is not None:
        try:
            import findings_store
            findings_store.write_kind(Path(ticket_dir),
                                      findings_store.STORE_KIND_BY_KEY[kind.name], 1,
                                      list(output.findings))
        except (OSError, ValueError, KeyError, TypeError):
            pass  # degrade-not-fail: recording is best-effort
    return records


# --- track scaling ----------------------------------------------------------

def review_mode(track: str | None, signals: dict | None = None) -> str:
    """Return the review mode for *track*: "full" | "cascade" | "skip".

    Per the epic matrix: full on M/L, cascade on S, skip on XS. A cascade stays
    a cascade here (the SIGNAL check lives in `should_run`) so callers can tell an
    S ticket apart from an M ticket.
    """
    t = (track or "").strip().upper()
    if t in ("M", "L"):
        return "full"
    if t == "S":
        return "cascade"
    if t == "XS":
        return "skip"
    # Unknown track: fail-safe toward doing the review rather than skipping it.
    return "full"


def _has_escalation_signal(signals: dict | None) -> bool:
    if not signals:
        return False
    if signals.get("scope_expansion") or signals.get("sentinel_hits"):
        return True
    risk = signals.get("risk_tags") or []
    return bool(_ESCALATING_RISK_TAGS.intersection(risk))


def should_run(track: str | None, signals: dict | None = None) -> bool:
    """Whether an independent review should run for this track+signals.

    full   -> always. skip -> never. cascade (S) -> only when a signal fires
    (risk_tags user-facing/data/security/migration/coordination, scope
    expansion, or sentinel hits), applying the review_cascade precedent.
    """
    mode = review_mode(track, signals)
    if mode == "full":
        return True
    if mode == "skip":
        return False
    return _has_escalation_signal(signals)


# --- the consume seam (wired into phase_completion at the ack decision gate) -

def consume_records(ticket_dir: Path, track: str | None, signals: dict | None = None,
                    kind: ReviewKind = SPEC_REVIEW,
                    persist: bool = True) -> tuple[list[dict], list[dict]]:
    """Record-shaped twin of `consume` (KLC-117). Same wording, same trigger
    logic, same order — only the carrier is a typed dict instead of a string.
    `consume` below is now a thin renderer over this function, so its 85
    existing regression assertions across the four review-binding test modules
    stay byte-compatible.

    Severity (Q-003 table): a routed decision, or a findings summary carrying
    at least one high finding, is HIGH; a findings summary with no high
    finding, a schema-validation note, and every "degraded" note (absent
    expected review / degraded reviewer output / consume exception) are MEDIUM.
    """
    def _rec(severity: str, code: str, message: str, ref: str = "") -> dict:
        return {"source": f"{kind.name}-review", "severity": severity,
                "code": f"{kind.name}-review.{code}", "message": message, "ref": ref}

    try:
        ticket_dir = Path(ticket_dir)
        expected = should_run(track, signals)
        path = ticket_dir / kind.output_file
        if not path.exists():
            if expected:
                msg = (f"{kind.name}-review: independent {kind.name} review expected "
                       f"for track {(track or '?').upper()} but no {kind.output_file} "
                       f"found (degraded)")
                return ([_rec("medium", "degraded", msg)], [])
            return ([], [])  # skip / no-signal cascade: nothing to surface

        text = path.read_text(encoding="utf-8")
        output = parse_review(text, kind)

        records: list[dict] = []
        if output.degraded:
            msg = (f"{kind.name}-review: reviewer output degraded "
                   f"({output.degrade_reason}); decisions_to_confirm unavailable")
            records.append(_rec("medium", "degraded", msg))
            return records, []

        for d in output.decisions_to_confirm:
            rec_ans = d.recommended.strip() or "(no recommendation given)"
            msg = (f"{kind.name}-review[decision {d.id}/{d.topic}]: {d.question} "
                   f"— RECOMMENDED: {rec_ans}")
            records.append(_rec("high", "decision", msg, ref=d.id))

        # KLC-127/D-106: an old-shape or otherwise invalid block raises exactly
        # ONE schema advisory and leaves any existing stored file untouched —
        # the findings summary and the write below never run on this path.
        errors = validate(output, kind)
        if errors:
            old = any(isinstance(r, dict) and k in r for r in output.raw_findings
                      for k in ("category", "detail", "suggested_fix"))
            hint = "; old shape: re-run the reviewer with the current finding schema" if old else ""
            records.append(_rec("medium", "schema",
                                f"{kind.name}-review[schema]: {len(errors)} error(s): "
                                f"{'; '.join(errors[:3])}{hint}"))
            return records, []

        if output.findings:
            highs = sum(1 for f in output.findings if f.severity.upper() in ("HIGH", "CRITICAL"))
            msg = (f"{kind.name}-review: {len(output.findings)} finding(s) recorded "
                   f"({highs} high) in findings.json — assess before build")
            records.append(_rec("high" if highs else "medium", "findings", msg))

        # Write only on the persisting (ack) path; a probe records nothing.
        findings = record_findings(output, ticket_dir if persist else None, kind)
        return records, findings
    except Exception as exc:  # noqa: BLE001 — the ack must never crash on review I/O
        return ([_rec("medium", "degraded", f"{kind.name}-review: consume degraded ({exc!r})")], [])


def consume(ticket_dir: Path, track: str | None, signals: dict | None = None,
            kind: ReviewKind = SPEC_REVIEW,
            persist: bool = True) -> tuple[list[str], list[dict]]:
    """Read the reviewer's verdict for a ticket and produce (advisories, findings).

    UNCHANGED contract: `(list[str], findings)`. Now a thin renderer over
    `consume_records` (KLC-117), so this seam's 85 existing regression
    assertions keep passing unmodified.

    This is the seam `phase_completion` calls at the discovery/design ack:
      * advisories -> appended to the ack's advisory lines (the decision gate the
        human already sees); carries every routed decision_to_confirm, a collapsed
        findings summary (so the OBJECTIVE primary output is not silent), and any
        schema-validation note.
      * findings   -> recorded to `findings.json` for the build
        phase to assess — but ONLY when `persist` is True. A read-only probe
        (`persist=False`, used by the klc hook's pending line / gate-policy signal collection)
        surfaces the same advisories WITHOUT writing (read-only verbs don't write).

    Degrade-not-fail: absent output on a review-expected track surfaces ONE note;
    absent output on a skip/no-signal track is silent; nothing here ever raises.
    """
    records, findings = consume_records(ticket_dir, track, signals, kind, persist)
    return [r["message"] for r in records], findings


# --- CLI --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description="independent artifact-review plumbing")
    ap.add_argument("--file", help="reviewer output file (the JSON-verdict block)")
    ap.add_argument("--track", default="M")
    ap.add_argument("--ticket-dir",
                    help="deprecated (KLC-127): no findings file is written here any "
                         "more — use `python3 core/skills/handback.py take` instead")
    args = ap.parse_args(argv)

    if args.ticket_dir:
        print("spec_review: --ticket-dir no longer writes a findings file "
              "(KLC-128); take a reviewer verdict in with "
              "`python3 core/skills/handback.py take --kind <kind> --ticket <KEY> "
              "--file <verdict>` instead", file=sys.stderr)

    text = Path(args.file).read_text(encoding="utf-8") if args.file else ""
    output = parse_review(text)
    errors = validate(output)
    result = {
        "mode": review_mode(args.track),
        "should_run": should_run(args.track),
        "degraded": output.degraded,
        "degrade_reason": output.degrade_reason,
        "schema_errors": errors,
        "routed_decisions": route_decisions(output),
        "findings": record_findings(output),   # KLC-127 AC-9: never persisted by the CLI
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
