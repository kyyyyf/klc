# KLC-034 — Design options

Design-level elaboration of the approaches in `spec.md`. The discovery pick
(Option A — minimal, reuse shipped patterns) is carried here as the design
decision; this file records the concrete shape Sonnet will build.

## Option A — minimal, reuse KLC-032/033 plumbing  *(chosen)*

- **AskUserQuestion (AC-1)**: edit the Socratic step (step 2) in
  `core/agents/discovery.md` and `core/agents/discovery-lite.md` to say: use the
  `AskUserQuestion` tool, one question per call, wait for the answer before the
  next; skip questioning entirely when context already resolves every material
  unknown. Keep the existing phrase "one question at a time" and the
  "2-3 approaches" marker so KLC-032's regression asserts stay green.
- **UPGRADE_M helper (AC-2)**: add to `core/skills/spec_structure.py`:
  `_UPGRADE_M_RE = re.compile(r"\bDISCOVERY_LITE_UPGRADE_M\b")` and
  `has_upgrade_m_signal(text) -> bool`, mirroring `has_decompose_signal`.
- **Advisory (AC-3)**: in `core/skills/phase_completion.can_complete_discovery_lite`,
  in the final "all checks passed" branch, after the `has_decompose_signal`
  check, add: `if has_upgrade_m_signal(text): return True, "DISCOVERY_LITE_UPGRADE_M: scope exceeds S — re-route via `klc retrack <KEY> M`"`.
  Non-blocking, parity with the decompose advisory.
- **Tests (AC-4, AC-5)**: one offline assert (`AskUserQuestion` token in both
  prompts) + the `has_upgrade_m_signal`/advisory unit tests in
  `tests/integration/test_socratic_gate.py` + one `judge()` behavioural fixture
  in `tests/test_prompt_regression.py` that skips without a key.
- **Docs (AC-6)**: `docs/process.md`, `docs/roles.md`, `docs/process-artifacts.md`.

Pros: smallest diff; identical patterns to the shipped, reviewed KLC-032 code;
advisory is additive and non-blocking so no risk to existing gate behaviour.
Cons: dialogue quality remains prompt-discipline (accepted — hybrid model).

## Option B — persisted questions log

Add a `questions-lite.md` artifact capturing each Q/A and gate on it. Rejected:
new artifact + gate + tests for marginal auditing value the roadmap does not ask
for. See `spec.md` Approaches.

## Option C — full conversational simulation harness

Multi-turn test loop asserting the agent waits between questions. Rejected:
heavy, brittle, needs live model turns; disproportionate to a three-gap
follow-up. See `spec.md` Approaches.

## DECISION D-001

Picked **Option A**. Mechanics (`has_upgrade_m_signal`, the advisory) are Python;
dialogue quality is prompt + behavioural judge. Consistent with KLC-032/033 and
the hybrid enforcement model. `impl-plan.md` carries the step breakdown.
