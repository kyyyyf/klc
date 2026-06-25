---
ticket: KLC-050
kind: tech
authority: human
last_generated: 2026-06-24
risk_tags: []
---

# KLC-050 — Gate hardening (judgment-side weaknesses)

## Goals

Close the four judgment-side gate weaknesses the 2026-06-24 quality review found, so the
gates resist trivial bypass rather than matching only one canonical shape. Four small,
independent fixes: broaden the no-pre-judgment lint, reject placeholder picks, make the
model-on-subagent guard actually reject, and unify the duplicate step parser plus retire the
stale plan templates.

## Problem / Context

The hybrid model leans on prompt-discipline for judgment, but several mechanical backstops
are weaker than they read. The no-pre-judgment lint matches only `do not flag X`-shaped
phrases and misses `don't flag`, `ignore this`, `treat as minor`, `downgrade it`.
`spec_structure.recorded_pick` accepts the verbatim template line `Picked: <approach>` as a
real decision. `model_guard.check_subagent_dispatch` returns a warning string the callers
print but never act on, despite the roadmap saying the guard should reject a dispatch with no
resolved model. And two parsers exist for `## step-N` (`phase_completion._impl_plan_steps`
vs `impl_plan_check.parse_impl_plan_steps`) alongside unused `core/templates/impl-plan*.j2`
that lack the fields the live gate now requires — latent drift traps. None changes what a
gate fundamentally does; each makes it harder to satisfy falsely.

## Acceptance Criteria

- [ ] AC-1: `lint_review_prompts.lint_text` flags `don't flag this`, `ignore this issue`,
  `treat as minor`, and `downgrade it`; negative fixtures confirm benign review prose is not
  flagged.
- [ ] AC-2: `spec_structure.recorded_pick` returns False for a placeholder pick
  (`Picked: <approach>` / `Picked: TBD`) and True only for a concrete pick.
- [ ] AC-3: `model_guard` exposes a strict path that returns a rejection (non-zero / raised)
  when a subagent dispatch has no resolved model; the build/runner dispatch paths consult it
  and refuse rather than only printing a note.
- [ ] AC-4: A single `## step-N` parser is used by both `phase_completion` and
  `impl_plan_check` (one removed in favour of the other); a test asserts they agree on a
  sample plan.
- [ ] AC-5: The stale `core/templates/impl-plan.md.j2` / `impl-plan-short.md.j2` are either
  removed or updated to carry the gate-required fields; a test asserts any shipped plan
  template renders a gate-passing skeleton.

## Non-goals

- Not redesigning the gates — only hardening the four named spots.
- Not changing the canonical token list shared via `prompt_harness` re-exports beyond what
  AC-1/AC-2 require.

## Approaches

- Option A — fix each weakness at its source with a regression test per item:
  - Pros: each fix is small, local, independently testable; directly closes a named finding.
  - Cons: touches four areas, but the changes are tiny and additive.
- Option B — defer the lint/pick hardening to prompt-discipline only and fix just the parser
  duplication:
  - Pros: smallest diff.
  - Cons: leaves the trivially-evadable gates the review flagged; the point of the ticket is
    to harden them. Rejected.

Picked: Option A — fix all four at the source with regression tests. (DECISION D-001)

## Affected

- `core/skills/lint_review_prompts.py` — broaden patterns.
- `core/skills/spec_structure.py` — placeholder-aware `recorded_pick`.
- `core/skills/model_guard.py` (+ `runner.py`, `build_orchestrator.py`) — strict reject path.
- `core/skills/phase_completion.py` / `impl_plan_check.py` — unify the step parser.
- `core/templates/impl-plan.md.j2`, `impl-plan-short.md.j2` — remove or align.
- `tests/integration/test_no_pre_judgment_lint.py`, `test_socratic_gate.py`,
  `test_model_subagent_guard.py`, `test_impl_plan_check.py` — regression coverage.
- `docs/process.md` — note the hardened gates.

## Estimate

| Axis | Score | Rationale |
|------|-------|-----------|
| complexity | 2 | Four small independent fixes. |
| uncertainty | 1 | Each weakness and its fix are precisely identified. |
| risk | 1 | Hardening only; existing valid inputs still pass. |
| manual | 0 | Fully covered by offline tests. |
| total | 4 | S. |
