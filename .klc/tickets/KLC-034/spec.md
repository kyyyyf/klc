---
ticket: KLC-034
kind: feature
authority: human
last_generated: 2026-06-22
risk_tags: []
---

# KLC-034 — AskUserQuestion + live re-route signals in the Socratic protocol

## Goals

Close the three residual gaps left by KLC-032 (archived) relative to KLC-SP
roadmap item 1.1, so the discovery Socratic protocol is enforced through real
mechanisms rather than prose:

1. The "ask one question at a time" rule is backed by the `AskUserQuestion` tool
   (one question per call), not just a sentence in the prompt.
2. `DISCOVERY_LITE_UPGRADE_M` becomes a live signal that `phase_completion`
   detects and surfaces as a re-route advisory, mirroring `DISCOVERY_DECOMPOSE`.
3. The one-question-at-a-time behaviour is covered by a behavioural harness
   fixture (a `judge()` check), not only a phrase-existence assertion.

## Problem / Context

KLC-032 shipped the structural half of the Socratic protocol: the
≥2-approaches/recorded-pick gate (`core/skills/spec_structure.py`,
`core/skills/phase_completion.py`), the `options-lite.md` artifact, the
`DISCOVERY_DECOMPOSE` advisory, and prompt markers in `discovery.md` /
`discovery-lite.md`. KLC-033 shipped spec self-review. Both are archived.

Three roadmap-1.1 items were out of KLC-032's acceptance criteria and remain:

- **AskUserQuestion is referenced nowhere in `core/agents/`.** The dialogue
  discipline is prose ("Ask one question at a time. Never batch questions.").
  The roadmap calls for the actual tool, one question per call.
- **`DISCOVERY_LITE_UPGRADE_M` is a dead signal.** It is emitted by
  `discovery-lite.md` (the prompt tells the agent to emit it when scope exceeds
  S) but no skill detects it — only `DISCOVERY_DECOMPOSE` is surfaced by
  `phase_completion`. The operator never sees the re-route hint.
- **Behaviour is not tested.** `tests/test_prompt_regression.py` asserts the
  phrase "one question at a time" exists in the prompt; nothing checks that the
  agent actually asks one question and defers the rest.

## Acceptance Criteria

1. AC-1: `discovery.md` and `discovery-lite.md` instruct the agent to use the
   `AskUserQuestion` tool for the Socratic questioning step, asking exactly one
   question per call and waiting for the answer before the next; if context
   already answers every material unknown, the agent skips questioning and goes
   straight to the approaches step. The existing four-step Socratic block and
   its markers (the phrase "one question at a time", "2-3 approaches") are
   preserved.
2. AC-2: `core/skills/spec_structure.py` gains a `has_upgrade_m_signal(text)`
   helper (regex on the `DISCOVERY_LITE_UPGRADE_M` token), mirroring
   `has_decompose_signal`, with no duplicated regex elsewhere.
3. AC-3: `core/skills/phase_completion.can_complete_discovery_lite` surfaces a
   non-blocking re-route advisory when `DISCOVERY_LITE_UPGRADE_M` is present in
   the spec, pointing the operator at `klc retrack <KEY> M`. The advisory does
   not block ack (parity with the `DISCOVERY_DECOMPOSE` advisory).
4. AC-4: A prompt-regression test asserts both discovery prompts contain
   `AskUserQuestion`; it fails on the pre-change prompts and passes after the
   AC-1 edit (kept as a permanent regression guard, not xfail).
5. AC-5: A behavioural harness fixture uses `judge()` to verify the agent's
   first turn asks exactly one question and does not batch; it skips gracefully
   when no judge API key is set (CI-safe) and exercises the wired prompt locally.
6. AC-6: Docs reflect the new reality with no stale claims: `docs/process.md`
   (discovery uses AskUserQuestion; `DISCOVERY_LITE_UPGRADE_M` is a live re-route
   signal alongside `DISCOVERY_DECOMPOSE`), `docs/roles.md` (discovery role asks
   one question at a time via the tool), `docs/process-artifacts.md`
   (`options-lite.md` and the two re-route signals).

## Non-goals

- Not changing the 4-axis track scoring or routing (KLC-028 owns that).
- Not implementing decompose/upgrade mechanics (how a ticket is actually split
  or re-tracked automatically) — only making the signal live and advisory.
  Auto-retrack on the signal is a future ticket.
- Not re-opening KLC-032's shipped structural gate or `options-lite.md` format.

## Approaches

- Option A — minimal, reuse shipped patterns: prompt edit adds an
  `AskUserQuestion` directive to the existing Socratic step; add
  `has_upgrade_m_signal` next to `has_decompose_signal`; surface the advisory in
  the existing discovery-lite advisory branch; add one prompt-regression assert
  and one `judge()` fixture. Smallest diff, highest consistency with KLC-032/033.
  - Pros: tiny surface area; reuses `has_decompose_signal` and the advisory
    plumbing verbatim; no new artifacts; low regression risk.
  - Cons: dialogue quality stays prompt-discipline (acceptable per the hybrid
    model — judgment is prompt + harness, mechanics are gates).
- Option B — add a structured questions-log artifact: persist each asked
  question/answer to `questions-lite.md` and gate on its presence.
  - Pros: a mechanical trace of the dialogue; auditable.
  - Cons: new artifact + new gate + new tests for marginal value; the roadmap
    only asks for the tool and behaviour, not a persisted log; higher cost.
- Option C — full conversational simulation harness: drive a multi-turn loop in
  tests to assert the agent waits between questions.
  - Pros: strongest behavioural guarantee.
  - Cons: heavy harness work, brittle, needs live model turns; disproportionate
    to a three-gap follow-up.

Picked: Option A — minimal and consistent with the shipped KLC-032/033
mechanisms; mechanics go to Python gates, dialogue quality stays prompt +
behavioural-judge per the hybrid enforcement model. (DECISION D-001)

## Estimate

| Axis | Score | Rationale |
|------|-------|-----------|
| complexity | 2 | Prompt edits + one helper + one advisory branch + two tests. |
| uncertainty | 1 | Patterns already exist (`has_decompose_signal`, advisory branch, `judge()`). |
| risk | 1 | Additive; no change to shipped gate behaviour; advisory is non-blocking. |
| manual | 1 | Behavioural judge fixture is best exercised locally with an API key. |
| total | 5 | M (feature spanning prompts, skills, tests, docs). |
