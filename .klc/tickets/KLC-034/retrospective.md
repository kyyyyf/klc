---
ticket: KLC-034
authority: human
---

# Retrospective — KLC-034

## What shipped

- `core/skills/spec_structure.py`: `has_upgrade_m_signal` helper (mirrors `has_decompose_signal`).
- `core/skills/phase_completion.py`: advisory accumulator for both `DISCOVERY_DECOMPOSE` and `DISCOVERY_LITE_UPGRADE_M` — both signals now surface when both are present.
- `core/agents/discovery.md`, `core/agents/discovery-lite.md`: `AskUserQuestion` directive in the Socratic step 2.
- `tests/integration/test_socratic_gate.py`: 3 new tests (helper, advisory, both-signals).
- `tests/test_prompt_regression.py`: 2 new guards (AskUserQuestion phrase, two-step behavioural judge fixture).
- `tests/fixtures/klc-034-socratic-input.md`: multi-unknown fixture for the judge test.
- `docs/process.md`, `docs/roles.md`, `docs/process-artifacts.md`: docs parity.

## What we learned

[!FACT F-R001] The advisory accumulator pattern (collect into `_advisories`, join with `"; "`) is now the canonical way to surface multiple non-blocking signals from `can_complete_*`. Both the DECOMPOSE and UPGRADE_M signals should be checked independently and combined rather than early-returning on the first match. src=core/skills/phase_completion.py:359 verified=2026-06-25

[!FACT F-R002] The "judge evaluates prompt text" pattern (phrase + rubric) is too weak for behavioural ACs — it duplicates phrase-regression coverage. True behavioural tests must run the prompt through a model (`_run_first_turn`) and score the actual response. src=tests/test_prompt_regression.py verified=2026-06-25

## Metrics

- Steps: 5 + 2 post-Codex fixes
- Suite: 458 passed, 12 skipped
- Codex findings: 2 MEDIUM (both fixed), internal reviewer: 1 LOW (fixed), 1 LOW (won't fix)
