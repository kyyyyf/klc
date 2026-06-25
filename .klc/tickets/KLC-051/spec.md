---
ticket: KLC-051
kind: tech
authority: human
last_generated: 2026-06-25
risk_tags: []
---

# KLC-051 — Plan-quality gate (anti-under-implementation discipline)

## Goals

Catch the recurring "specced-but-unwired" defect class at PLANNING time rather than after
build. Two adversarial audits of the KLC-SP tickets found the same pattern repeatedly:
impl-plan code sketches that call APIs which do not exist (`scan_sentinels.scan` vs the real
`scan_diff`), helpers defined but never wired into a real call site, tests that exercise a
private helper instead of the public entry point, and gates with no negative/bypass test.
KLC-051 adds a mechanical API-existence gate plus prompt-discipline rules (end-to-end and
negative-test coverage) and a standard adversarial-audit prep step, so plans are unambiguous
and complete before a Sonnet agent builds them.

## Problem / Context

The plan-completeness gate (KLC-036, `core/skills/impl_plan_check.py`) checks that each
`## step-N` carries the required fields and no placeholder tokens. It does NOT verify that the
APIs named in code sketches exist, that new symbols get wired into a call site, or that the
test plan exercises public entry points and negative cases. Those are exactly the gaps the
audits kept finding. The hybrid model says: make the mechanical part a blocking gate, and the
judgment part prompt-discipline verified by the prompt-regression harness (KLC-029) and the
agent-side self-review (KLC-037). API-existence is mechanical and tractable (extract
`module.attr(` references, resolve the attr against the named module). The "end-to-end +
negative test" requirement is judgment, so it lives in the planning prompts and is checked by
a harness assert and the agent self-review. A standard adversarial completeness-audit (a fresh
subagent reading spec/test-plan/impl-plan) is the planning analog of the mandatory
code-reviewer already required before review-report.

## Acceptance Criteria

- [ ] AC-1: A new skill `core/skills/plan_quality.py::unresolved_api_refs(impl_plan_text) ->
  list[str]` extracts `<module>.<attr>(` references from the impl-plan, and for every
  `<module>` that is the basename of a real `core/skills/*.py` module, flags any `<attr>` not
  defined in that module. It only flags references to PRE-EXISTING modules (a symbol introduced
  by the same plan is not flagged), and it ignores leading names that are not core/skills
  modules (stdlib/third-party/pseudocode), to stay low-false-positive.
- [ ] AC-2: `unresolved_api_refs` is wired into the plan-completeness path so a design (M/L)
  or discovery-lite (S) ack is BLOCKED when the impl-plan references a nonexistent attribute of
  a known module. A negative test proves `scan_sentinels.scan(` blocks and `scan_sentinels.scan_diff(`
  passes; the wiring is exercised through the real `can_complete_*` entry point, not the helper.
- [ ] AC-3: Both planning prompts (`core/agents/design.md`, `core/agents/discovery-lite.md`)
  and the test-planner (`core/agents/test-planner.md`) carry a rule: every AC describing a CLI,
  gate, or wired behaviour maps to an end-to-end test at the PUBLIC entry point (not a private
  helper), and every gate/validator AC maps to a negative test (the gate bites) plus a
  fail-closed test (unavailable input is blocked).
- [ ] AC-4: A prompt-regression test (using the KLC-029 harness) asserts the end-to-end +
  negative-test rule is present in all three planning prompts, so the discipline cannot
  silently regress.
- [ ] AC-5: The agent-side self-review (KLC-037) runs `unresolved_api_refs` over the impl-plan
  before emitting and fixes or flags any unresolved reference inline.
- [ ] AC-6: `docs/process.md` documents the plan-quality gate, and the project guidance adds an
  adversarial completeness-audit (fresh subagent over spec/test-plan/impl-plan) as a standard
  step before declaring a ticket build-ready — the planning analog of the mandatory
  code-reviewer.

## Non-goals

- Not resolving aliased imports (`import ack as ack_cmd`) — the check is deliberately
  conservative, matching only literal `<skill-module>.<attr>(` to keep false positives near zero.
- Not a full static type-check of code sketches; only the named-attribute existence on known
  modules.
- Not mechanically verifying the end-to-end/negative-test rule per ticket (that stays
  judgment — prompt + harness + audit), only that the prompts carry the rule.

## Approaches

- Option A — mechanical API-existence gate + prompt-discipline for the test-coverage rule +
  agent self-review hook + documented audit step:
  - Pros: splits cleanly along the hybrid line (mechanical where tractable, judgment where not);
    API-existence is high-value and low-false-positive when scoped to known modules; reuses the
    KLC-036 gate path, the KLC-029 harness, and the KLC-037 self-review; each piece is small.
  - Cons: the test-coverage rule is enforced by prompt + audit, not a hard gate — accepted,
    because a mechanical "is this test end-to-end" check is infeasible without heavy heuristics.
- Option B — make the end-to-end/negative-test rule a hard Python gate too (parse the test plan,
  classify each test as unit vs integration, match to ACs):
  - Pros: fully mechanical.
  - Cons: classifying a test as "end-to-end at the public entry point" is heuristic and noisy;
    a flaky gate erodes trust (the opposite of the goal). Rejected.
- Option C — documentation/checklist only, no code:
  - Pros: zero code.
  - Cons: leaves the invented-API class uncaught mechanically — the single most concrete,
    automatable finding from the audits. Rejected.

Picked: Option A — mechanical API-existence gate + prompt-discipline + self-review + documented
audit step. (DECISION D-001)

## Affected

- `core/skills/plan_quality.py` (new) — `unresolved_api_refs`.
- `core/skills/phase_completion.py` — wire the check into design + discovery-lite ack.
- `core/agents/design.md`, `core/agents/discovery-lite.md`, `core/agents/test-planner.md` —
  the end-to-end + negative-test rule and the self-review hook.
- `tests/integration/test_plan_quality.py` (new), `tests/test_prompt_regression.py`.
- `docs/process.md` — the gate + the adversarial-audit prep step.

## Estimate

| Axis | Score | Rationale |
|------|-------|-----------|
| complexity | 3 | A new extractor/resolver, a gate wiring, prompt rules, a harness assert, a self-review hook. |
| uncertainty | 2 | The extractor's false-positive scoping needs care; the rest reuses known patterns. |
| risk | 1 | Additive; the new gate only blocks genuinely nonexistent API references. |
| manual | 1 | One manual run of the gate against a planted bad reference. |
| total | 7 | M (tech change spanning a skill, a gate, prompts, harness, docs). |
