#!/usr/bin/env python3
"""implplan_review.py — the THIRD binding of KLC-084's independent-artifact-review
seam, this time onto `impl-plan.md` (KLC-094 / V-01).

The mandatory external code reviewer checks CODE against the spec "as written";
KLC-084 shifted that discipline LEFT onto `spec.md`, KLC-085 onto `test-plan.md`,
and V-01 completes the trilogy on the implementation PLAN. A fresh, adversarial
reviewer reads `impl-plan.md` against the spec's SAOC acceptance criteria AND the
already-recorded spec-review findings, and emits the two output classes the seam
carries: OBJECTIVE `findings[]` (a missing step, a step depending on a later one, a
step with no verifiable RED outcome, an AC/spec-review-finding no step addresses, a
step whose RED-before-GREEN cannot hold) and SUBJECTIVE `decisions_to_confirm[]`
(a sequencing tradeoff, a scope boundary), each with a recommended answer.

Reuse (C-001 — no fork): this module carries ONLY the `IMPL_PLAN_REVIEW` descriptor
and a thin `consume` wrapper delegating to `spec_review.consume`. The generic seam
(`core/skills/spec_review.py`) reads its category/topic vocabulary FROM the
descriptor, so `validate`, `route_decisions`, `summarize_findings`,
`record_findings` and `consume` all carry the impl-plan flavour UNCHANGED — there is
no second parser, validator, or router. This mirrors `testplan_review.py` exactly.

Degrade-not-fail (C-005): a missing / malformed / absent reviewer output degrades
to a single surfaced note; nothing here ever raises. That guarantee already lives
inside `spec_review.consume`; this wrapper adds nothing to it.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Package-safe path setup (mirrors testplan_review.py): make both the project root
# and this skills dir importable so a bare `import spec_review` resolves under
# script AND package invocation.
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
for _p in (str(_project_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import spec_review as _spec_review  # noqa: E402

# The impl-plan flavour of KLC-084's generic independent-artifact-review seam.
# The ONLY things that differ from SPEC_REVIEW / TEST_PLAN_REVIEW are the reviewer
# prompt, the artifact under review, the file the reviewer writes its verdict to,
# and — crucially — the OBJECTIVE finding categories and SUBJECTIVE decision topics.
# Because that vocabulary lives on the kind (not module-global in spec_review),
# `spec_review.validate`/`route_decisions`/`summarize_findings`/`record_findings`/
# `consume` all carry it through UNCHANGED — no forked parser/validator/router.
#
#   finding_categories (OBJECTIVE — the reviewer decides, the implementer assesses):
#     missing-step          an AC / behaviour no step builds
#     wrong-sequencing      a step depends on the output of a later step
#     untestable-step       a step has no RED / verifiable outcome
#     unaddressed-ac        an AC — or a recorded spec-review finding — no step addresses
#     infeasible-red-green  a step whose RED-before-GREEN ordering cannot hold
#   decision_topics (SUBJECTIVE — elevated to the human at the ack decision gate):
#     sequencing-tradeoff   two defensible step orders; which to commit to
#     scope                 a plan boundary — is this step's work in or out?
IMPL_PLAN_REVIEW = _spec_review.ReviewKind(
    name="impl-plan",
    reviewer_prompt="core/agents/impl-plan-reviewer.md",
    artifact="impl-plan.md",
    output_file="impl-plan-review.md",
    finding_categories=("missing-step", "wrong-sequencing", "untestable-step",
                        "unaddressed-ac", "infeasible-red-green"),
    decision_topics=("sequencing-tradeoff", "scope"),
)


def consume(ticket_dir, track, signals=None, persist: bool = True):
    """Consume the independent `impl-plan-reviewer` verdict for this ticket.

    Thin binding of KLC-084's generic seam to `IMPL_PLAN_REVIEW`: it delegates
    straight to `spec_review.consume`, so the impl-plan review reuses the SAME
    parser, validator, decision-router, findings-summariser and findings-recorder
    that the spec and test-plan reviews use — the schema-generic seam carries the
    impl-plan finding categories / decision topics off `IMPL_PLAN_REVIEW`. Returns
    `(advisories, findings)`; degrade-not-fail lives inside `spec_review.consume`.
    `persist=False` (a read-only probe: `klc remind` / gate-policy) surfaces the
    advisories WITHOUT writing `impl-plan-review-findings.json`.
    """
    return _spec_review.consume(
        ticket_dir, track, signals, kind=IMPL_PLAN_REVIEW, persist=persist
    )
