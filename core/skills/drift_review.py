#!/usr/bin/env python3
"""drift_review.py — the FOURTH binding of KLC-084's independent-artifact-review seam
(DRIFT_CHECK, KLC-099 / drift-check epic D-04).

KLC-084 shifted the mandatory-external-reviewer discipline onto `spec.md`, KLC-085 onto
`test-plan.md`, KLC-094 onto `impl-plan.md`. This fourth binding shifts it onto the built
DIFF vs the ticket's RECORDED design decisions: a fresh, adversarial reviewer reads
`git diff` + the inline `[!DECISION D-nnn]` items (`items.py`) + `spec.md` and flags where
the code appears to drift from the SPIRIT of a decision — the SUBJECTIVE judgment
complement to KLC-098's DETERMINISTIC scope/step drift. It emits the seam's two output
classes: OBJECTIVE `findings[]` (a diff that contradicts a recorded decision, a de-facto
decision the diff makes but never records, a drift from the spec's own words) and
SUBJECTIVE `decisions_to_confirm[]` (was a deviation intentional? did a decision get
superseded?), each with a recommended answer.

Reuse (C-001 — no fork): this module carries ONLY the `DRIFT_CHECK` descriptor and a thin
`consume` wrapper delegating to `spec_review.consume`. The generic seam
(`core/skills/spec_review.py`) reads its category/topic vocabulary FROM the descriptor, so
`validate`, `route_decisions`, `summarize_findings`, `record_findings` and `consume` all
carry the drift flavour UNCHANGED — no second parser, validator, or router. This mirrors
`implplan_review.py` exactly.

Degrade-not-fail (C-002): a missing / malformed / absent reviewer output degrades to a
single surfaced note; nothing here ever raises. That guarantee already lives inside
`spec_review.consume`; this wrapper adds nothing to it. Surface-only: fail-open, never blocks.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Package-safe path setup (mirrors implplan_review.py): make both the project root and
# this skills dir importable so a bare `import spec_review` resolves under script AND
# package invocation.
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
for _p in (str(_project_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import spec_review as _spec_review  # noqa: E402

# The drift flavour of KLC-084's generic independent-artifact-review seam. The ONLY things
# that differ from SPEC_REVIEW / TEST_PLAN_REVIEW / IMPL_PLAN_REVIEW are the reviewer
# prompt, the artifact under review, the output file, and the OBJECTIVE finding categories
# and SUBJECTIVE decision topics. Because that vocabulary lives on the kind (not
# module-global in spec_review), `spec_review.validate`/`route_decisions`/`summarize_findings`/
# `record_findings`/`consume` all carry it through UNCHANGED — no forked parser/validator/router.
#
#   finding_categories (OBJECTIVE — the reviewer decides, the operator assesses):
#     decision-violation  — the diff contradicts a recorded [!DECISION D-nnn].
#     unrecorded-decision — the diff makes a de-facto design decision it never records.
#     spec-drift          — the diff drifts from the spec's own stated behaviour.
#   decision_topics (SUBJECTIVE — the reviewer NEVER adjudicates; it elevates to the human):
#     intentional-deviation   — is a departure from a decision deliberate (record it) or a bug?
#     decision-supersession   — does the diff supersede an older decision (needs a new D-nnn)?
DRIFT_CHECK = _spec_review.ReviewKind(
    name="drift",
    reviewer_prompt="core/agents/drift-reviewer.md",
    artifact="the built diff (git diff) vs recorded D-NNN decisions",
    output_file="drift-review.md",
    finding_categories=("decision-violation", "unrecorded-decision", "spec-drift"),
    decision_topics=("intentional-deviation", "decision-supersession"),
)


def consume(ticket_dir, track, signals=None, persist: bool = True):
    """Thin delegate to `spec_review.consume` bound to DRIFT_CHECK — no fork (C-001).

    Returns (advisories, findings) exactly as the seam does; degrade-not-fail and the
    read-only-on-`persist=False` discipline live inside the seam."""
    return _spec_review.consume(ticket_dir, track, signals, kind=DRIFT_CHECK, persist=persist)
