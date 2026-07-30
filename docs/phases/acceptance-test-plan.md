# Acceptance-test-plan phase

## Purpose
Map every AC to concrete acceptance/e2e tests. No implementation details yet.

## Inputs
- `spec.md`

## Outputs
- `test-plan.md` — Acceptance coverage table, edge cases, regression scenarios, manual checklist (if estimate.manual ≥ 2)

## Process
Agent writes test-plan.md with:
- Table: AC | Test type (e2e/acceptance/manual) | Test location | Notes
- Edge cases from spec
- Regression scenarios for affected modules
- Manual checklist if needed

## Completion criteria
- Every AC has a row in acceptance coverage table
- Test types are e2e/acceptance/manual (no unit/integration yet)
- Manual checklist populated if estimate.manual ≥ 2

## Independent coverage review (KLC-085)
Before the phase completes, an independent, adversarial COVERAGE review runs against
the spec's SAOC ACs. Two layers, both surfaced at ack as **warn-only advisories**
(no new blocking gate — an uncovered AC is already a phase-failure via the planner):

- The **independent reviewer** (`core/agents/test-plan-reviewer.md`) writes its
  verdict to `test-plan-review.md`. It reuses KLC-084's generic
  independent-artifact-review seam (`core/skills/spec_review.py`) bound to
  `testplan_review.TEST_PLAN_REVIEW`: the OBJECTIVE `findings[]` (categories
  `uncovered-ac` / `weak-assertion` / `missing-edge-case`) are recorded to
  `test-plan-review-findings.json` for the build phase to assess, and the SUBJECTIVE
  `decisions_to_confirm[]` (topics `coverage-depth` / `risk-prioritization`) are
  routed to the human at the ack decision gate. There is no forked parser/validator.
- The **deterministic pre-pass** (`core/skills/testplan_review.py`) maps each AC to a
  planned test and surfaces uncovered ACs, happy-path-only plans, and gate/reject ACs
  missing a negative case.

Scope is coverage DESIGN only — whether a test is implemented / not-faked in code
stays the code reviewer's job. Track-scaled: full on M/L, cascade on S, skipped on
XS. Findings are recorded only on the persisting (ack) path; a read-only probe
(`klc remind`, gate-policy) surfaces the same advisories without writing.
Degrade-not-fail: absent ACs / test-plan / reviewer output → a single surfaced note,
never a crash.

## Ack options
- `--pick 1` (approve): Advance based on track
  - S → build:work
  - M/L → design:work
- `--pick 2` (needs-rework): Agent revises test-plan.md

## Common pitfalls
- Missing AC in table → phase failure
- Using unit/integration test types (those are phase 4 concern)
- No manual checklist when estimate.manual ≥ 2

## Example
S ticket: AC-1, AC-2, AC-3 → 3 rows in table → approve → build:work  
M ticket: AC-1, AC-2 → 2 rows → approve → design:work
