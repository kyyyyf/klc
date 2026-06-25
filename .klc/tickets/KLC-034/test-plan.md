---
ticket: KLC-034
kind: acceptance-test-plan
last_generated: 2026-06-22
---

# KLC-034 — Acceptance test plan

Maps each acceptance criterion to its verification. Mechanical checks are
offline pytest; dialogue-quality checks use the `judge()` harness helper and
skip gracefully without an API key.

## Acceptance coverage

| AC | What it asserts | Test / verification | Type |
|----|-----------------|---------------------|------|
| AC-1 | Both discovery prompts instruct one `AskUserQuestion` call per question and preserve the Socratic markers | `tests/test_prompt_regression.py::test_discovery_prompts_use_askuserquestion` (token present in both prompts) + existing `test_discovery_prompts_have_socratic_step` still green | offline |
| AC-2 | `spec_structure.has_upgrade_m_signal` detects the `DISCOVERY_LITE_UPGRADE_M` token and not absence | unit test in `tests/integration/test_socratic_gate.py` (present → True, absent → False) | offline |
| AC-3 | `can_complete_discovery_lite` returns a non-blocking re-route advisory mentioning `klc retrack` when the signal is present | `tests/integration/test_socratic_gate.py`: spec ending in `DISCOVERY_LITE_UPGRADE_M` → `(True, advisory)` where advisory mentions retrack | offline |
| AC-4 | The AskUserQuestion regression assert fails before the prompt edit, passes after | run the AC-1 test against pre-change prompt (red) and post-change (green); keep as permanent guard | offline |
| AC-5 | Agent's first turn asks exactly one question, no batching | `tests/test_prompt_regression.py` behavioural fixture via `judge()`; skips without API key, judges the wired prompt with key | judge (skips in CI) |
| AC-6 | Docs name AskUserQuestion + `DISCOVERY_LITE_UPGRADE_M` as live; no stale claims | `grep -rn "AskUserQuestion\|DISCOVERY_LITE_UPGRADE_M" docs/` returns the new content; manual read of the three docs | manual/grep |

## Edge cases

- Signal token appears inside a fenced code block in the spec — detection should
  match the prompt-emitted signal but the advisory must not fire on a mere
  documentation mention; align behaviour with how `has_decompose_signal` treats
  the token (current behaviour is a plain token regex — document the known
  false-positive rather than silently diverging).
- Both `DISCOVERY_DECOMPOSE` and `DISCOVERY_LITE_UPGRADE_M` present — advisory
  must report both, not just the first, or pick a deterministic precedence and
  state it.
- Context already answers all unknowns — the prompt must allow skipping the
  questioning step (no `AskUserQuestion` call) without failing AC-1's intent.
- No judge API key in CI — the behavioural fixture (AC-5) must `pytest.skip`,
  never fail, so CI stays green.
- XS track reaching discovery-lite — XS is exempt from the approaches gate;
  the new advisory must not introduce an XS regression.

## Out of scope

- Auto-retrack on the signal (this ticket only surfaces the advisory).
- Persisted questions log (rejected Option B in spec.md).
