---
ticket: KLC-034
authority: generated
review_depth: full
reviewer: internal + external-subagent
reviewed_at: 2026-06-25
verdict: approved
---

# Review report — KLC-034

## AC verification

| AC | Status | Evidence |
|----|--------|---------|
| AC-1 | PASS | `AskUserQuestion` directive added to Socratic step 2 in both `core/agents/discovery.md:208` and `core/agents/discovery-lite.md:162`. "one question at a time" and "2-3 approaches" markers preserved. |
| AC-2 | PASS | `has_upgrade_m_signal` added at `core/skills/spec_structure.py:51`, using module-level `_UPGRADE_M_RE` (line 13). Mirrors `has_decompose_signal` exactly. No duplicated regex elsewhere. |
| AC-3 | PASS | Advisory branch at `phase_completion.py:363–364` returns `(True, "DISCOVERY_LITE_UPGRADE_M: scope exceeds S — re-route via 'klc retrack <KEY> M'")`. Non-blocking, "retrack" in message, parity with DECOMPOSE. |
| AC-4 | PASS | `test_discovery_prompts_use_askuserquestion` in `tests/test_prompt_regression.py` — permanent guard (no xfail). Verified RED on pre-step-2 commits via `git show HEAD~2`. |
| AC-5 | PASS | `test_one_question_at_a_time_judge_fixture` in `tests/test_prompt_regression.py` — skips gracefully without API key (calls `pytest.skip` via `judge_available()`). Fixture at `tests/fixtures/klc-034-socratic-input.md`. |
| AC-6 | PASS | `docs/process.md` — "Discovery Socratic protocol (KLC-034)" section added with AskUserQuestion + live signal table. `docs/roles.md` — discovery activity updated to cite AskUserQuestion. `docs/process-artifacts.md` — `options-lite.md` entry + per-artifact schema with both re-route signals. |

## Internal code-reviewer findings (fresh subagent)

A fresh (non-fork) code-reviewer subagent reviewed all 10 changed files.

### Finding LOW-1: Test asymmetry in advisory message assertions

**Finding**: `test_upgrade_m_signal_recognized` only asserted `"retrack" in msg`, while `test_decompose_signal_recognized` asserts `"DISCOVERY_DECOMPOSE" in msg`. A future refactor could change the signal token in the message and the UPGRADE_M test would still pass.

**Assessment**: FIXED — added `assert "DISCOVERY_LITE_UPGRADE_M" in msg` to mirror the DECOMPOSE pattern exactly.

### Finding LOW-2: `has_upgrade_m_signal` not re-exported from prompt_harness.py

**Finding**: Pattern is consistent with `has_decompose_signal` (also not exported). No consumer imports via harness. Not a regression.

**Assessment**: WON'T FIX — consistent with existing pattern; no consumer requires it.

## External (Codex) review findings

Codex reviewed the branch at `3d98029..c5bf496`, verdict: CHANGES REQUESTED.

### MEDIUM-1: UPGRADE_M suppressed when DECOMPOSE also present

**Finding**: `can_complete_discovery_lite` early-returned on DECOMPOSE without checking UPGRADE_M, so both-signal specs never surface the retrack advisory. Contradicts AC-3 and the test plan both-signals case.

**Assessment**: FIXED — replaced two early-return branches with an `_advisories` accumulator that checks both signals and joins them with `"; "`. Added `test_both_signals_both_surfaced` (RED then GREEN) to cover the case.

### MEDIUM-2: Behavioural judge fixture evaluated prompt text, not agent first turn

**Finding**: The step-4 judge test passed the prompt instructions as "output to evaluate", which duplicated phrase-regression coverage rather than verifying actual agent behavior.

**Assessment**: FIXED — redesigned as a two-step test: (1) run `_run_first_turn()` to simulate the agent's actual first response using the discovery-lite Socratic excerpt + fixture, (2) judge that response with a rubric checking for exactly one question per turn.

## Suite result

```
458 passed, 12 skipped (post-Codex fixes)
```

## Verdict

**APPROVED** — all ACs satisfied, two Codex MEDIUMs fixed, one LOW fixed, one LOW acceptable.


---
[!CONFLICT] scope-expansion detected at review:ack-needed
  planned modules: ['core/agents', 'core/skills', 'tests', 'docs']
  actual modules:  ['core/agents', 'core/skills', 'docs', 'phase_completion', 'tests']
  unplanned:       ['phase_completion']
Resolve: update meta.json:affected_modules to include all touched modules, then re-run `klc ack KLC-034`.
