---
ticket: KLC-034
kind: impl-plan
design_choice: option-A-minimal
last_generated: 2026-06-22
---

# KLC-034 — Implementation plan (executable, for Sonnet)

Build target: close the three residual roadmap-1.1 gaps left by KLC-032.
Per-step contract: **Goal / RED / GREEN / VERIFY / COMMIT / Affected / Depends-on**.
Behaviour-changing steps carry a RED test first; prompt/doc-only steps use
`RED: not applicable` with the rule cited for the reviewer.

Run after each step: `python3 -m pytest tests/ -q`. Use COMMIT subjects verbatim.
All paths are repo-relative to the framework root.

## step-1 — has_upgrade_m_signal helper + advisory in phase_completion

- Goal: make `DISCOVERY_LITE_UPGRADE_M` a live signal — detected and surfaced as
  a non-blocking re-route advisory, mirroring `DISCOVERY_DECOMPOSE`. (AC-2, AC-3)
- RED: in `tests/integration/test_socratic_gate.py` add two cases —
  (a) `has_upgrade_m_signal` returns True on a spec containing the token and
  False on one without; (b) a complete S-track discovery-lite ticket whose
  `spec.md` ends with `DISCOVERY_LITE_UPGRADE_M` makes
  `phase_completion.can_complete_discovery_lite` return `(True, advisory)` with
  `advisory` containing "retrack". Both fail today (no helper, no branch).
- GREEN: in `core/skills/spec_structure.py` add
  `_UPGRADE_M_RE = re.compile(r"\bDISCOVERY_LITE_UPGRADE_M\b")` and
  `has_upgrade_m_signal(text)` mirroring `has_decompose_signal`. In
  `core/skills/phase_completion.py::can_complete_discovery_lite`, in the
  "all checks passed" tail (next to the `has_decompose_signal` advisory), add:
  `if _spec_structure.has_upgrade_m_signal(text): return True, "DISCOVERY_LITE_UPGRADE_M: scope exceeds S — re-route via 'klc retrack <KEY> M'"`.
  Keep it after the decompose check; non-blocking.
- VERIFY: `python3 -m pytest tests/integration/test_socratic_gate.py -q`.
- COMMIT: `KLC-034 step-1: detect + surface DISCOVERY_LITE_UPGRADE_M as re-route advisory`
- Affected: `core/skills/spec_structure.py`, `core/skills/phase_completion.py`,
  `tests/integration/test_socratic_gate.py`.
- Depends-on: none.

## step-2 — wire AskUserQuestion into the Socratic step

- Goal: back the one-question-at-a-time rule with the `AskUserQuestion` tool,
  one question per call. (AC-1)
- RED: not applicable for the prompt edit; add the regression guard in step-3.
  Rule cited: roadmap 1.1 — "AskUserQuestion по одному".
- GREEN: in both `core/agents/discovery.md` and `core/agents/discovery-lite.md`,
  in the Socratic step 2 ("Ask one question at a time. Never batch questions."),
  add: *use the `AskUserQuestion` tool, exactly one question per call, and wait
  for the answer before asking the next; if the explored context already answers
  every material unknown, skip questioning and go straight to the approaches
  step.* Do not remove the phrase "one question at a time" or the "2-3 approaches"
  marker (KLC-032 asserts depend on them).
- VERIFY: `grep -n AskUserQuestion core/agents/discovery*.md` shows both;
  `python3 -m pytest tests/test_prompt_regression.py -q` — existing socratic
  asserts still green.
- COMMIT: `KLC-034 step-2: Socratic step uses AskUserQuestion, one question per call`
- Affected: `core/agents/discovery.md`, `core/agents/discovery-lite.md`.
- Depends-on: none.

## step-3 — AskUserQuestion regression assert

- Goal: a permanent guard that both prompts reference the tool. (AC-4)
- RED: add `test_discovery_prompts_use_askuserquestion` to
  `tests/test_prompt_regression.py` asserting `AskUserQuestion` appears in both
  `discovery.md` and `discovery-lite.md`. Confirm it is RED on the pre-step-2
  prompt (stash step-2 or run against `git show HEAD~:...`) and GREEN after.
- GREEN: the test itself (and step-2's edit makes it pass). Keep it permanent,
  not `xfail`.
- VERIFY: `python3 -m pytest tests/test_prompt_regression.py -k askuserquestion -q`.
- COMMIT: `KLC-034 step-3: regression guard for AskUserQuestion in discovery prompts`
- Affected: `tests/test_prompt_regression.py`.
- Depends-on: step-2.

## step-4 — behavioural one-question-at-a-time judge fixture

- Goal: verify the agent's first turn asks exactly one question and does not
  batch. (AC-5)
- RED: add a golden ticket fixture (a request with two or more genuine unknowns)
  under `tests/` and a test in `tests/test_prompt_regression.py` that runs the
  discovery-lite prompt through the harness and calls `judge()` with the rubric
  *"Does the agent's first response ask exactly one question and defer the rest,
  rather than batching multiple questions?"*. The test must `pytest.skip` when
  `judge_available()` is False (the `judge()` helper already skips — assert that
  path stays CI-safe).
- GREEN: the fixture + test, reusing `judge_available()` / `judge()` from
  `tests/prompt_harness.py`. No new prompt change (step-2 supplies the behaviour
  the judge scores).
- VERIFY: with a key set, `python3 -m pytest tests/test_prompt_regression.py -k one_question -q`
  judges and passes; with no key it skips. State which path ran in the build-log.
- COMMIT: `KLC-034 step-4: behavioural one-question-at-a-time judge fixture`
- Affected: `tests/test_prompt_regression.py`, new fixture file under `tests/`.
- Depends-on: step-2.

## step-5 — documentation parity

- Goal: docs describe the live reality; no stale claims. (AC-6)
- RED: not applicable (docs). Rule cited: roadmap 1.1 + AC-6.
- GREEN: `docs/process.md` — discovery/discovery-lite ask via `AskUserQuestion`;
  `DISCOVERY_LITE_UPGRADE_M` is a live re-route signal alongside
  `DISCOVERY_DECOMPOSE` (→ `klc retrack`). `docs/roles.md` — discovery role asks
  one question at a time via the tool. `docs/process-artifacts.md` — record the
  `options-lite.md` artifact and the two re-route signals.
- VERIFY: `grep -rn "AskUserQuestion\|DISCOVERY_LITE_UPGRADE_M" docs/` returns
  the new content; re-read the three files for stale claims.
- COMMIT: `KLC-034 step-5: docs parity for AskUserQuestion + live UPGRADE_M`
- Affected: `docs/process.md`, `docs/roles.md`, `docs/process-artifacts.md`.
- Depends-on: step-1, step-2.

## Notes for the implementer

- One logical commit per step; COMMIT subjects verbatim.
- `judge()` tests are CI-safe (skip without an API key). Exercise step-4 locally
  with the key set and note which path ran in the build-log.
- Do not reopen KLC-032's shipped gate or `options-lite.md` format; this ticket
  is additive only.
- Known wart (see test-plan Edge cases): the signal regexes are plain token
  matches, so a doc mention of the token can trip the advisory. Mirror
  `has_decompose_signal` behaviour rather than diverging; note it, don't silently
  "fix" it here.
