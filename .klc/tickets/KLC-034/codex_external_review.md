---
ticket: KLC-034
reviewer: codex
role: external
reviewed_ref: feature/klc-034
reviewed_range: 3d98029..c5bf496
verdict: CHANGES REQUESTED
---

# External review — KLC-034

## Findings

### [MEDIUM] `DISCOVERY_LITE_UPGRADE_M` is suppressed when decompose is also present

`can_complete_discovery_lite` checks `DISCOVERY_DECOMPOSE` first and returns immediately at `core/skills/phase_completion.py:361` through `core/skills/phase_completion.py:362`. The new upgrade advisory is only checked afterward at `core/skills/phase_completion.py:363` through `core/skills/phase_completion.py:364`, so a spec containing both `DISCOVERY_DECOMPOSE` and `DISCOVERY_LITE_UPGRADE_M` will never surface the upgrade/retrack advisory.

That contradicts AC-3's "when `DISCOVERY_LITE_UPGRADE_M` is present" behavior, and the test plan explicitly calls out the both-signals case. Build the advisory from all present signals, or document and test deterministic precedence. As written, the more specific S-to-M reroute hint is dropped exactly when another reroute signal is also present.

### [MEDIUM] The behavioural judge fixture does not run an agent first turn

AC-5 asks for a behavioural harness fixture that verifies the agent's first turn asks exactly one question and does not batch. The added test at `tests/test_prompt_regression.py:324` through `tests/test_prompt_regression.py:340` reads the prompt excerpt, embeds the fixture text into the rubric, and calls `H.judge("(evaluate the prompt instructions above, not an agent response)", rubric)`.

That judges whether the prompt says the right thing, not whether the wired prompt produces a first response with one question. This duplicates the phrase-regression coverage from `test_discovery_prompts_use_askuserquestion` and would still pass if the harness never ran the discovery prompt at all. The fixture should execute the discovery-lite prompt through the prompt harness against `tests/fixtures/klc-034-socratic-input.md`, capture the first model response, and then ask the judge to score that response for exactly one question / no batching.

## Verification

Static review only. I did not run tests because the request was to avoid modifying files, and pytest/import runs may create local cache files in this workspace.

## Verdict

CHANGES REQUESTED
