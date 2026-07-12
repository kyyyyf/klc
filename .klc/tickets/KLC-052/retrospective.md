---
ticket: KLC-052
authority: human
last_generated: 2026-07-12T00:00:00Z
---

# Retrospective — KLC-052

## What happened (facts, not opinions)

> [!FACT F-R1] src=meta.json:estimate
> estimate = {complexity: 3, uncertainty: 1, risk: 2, manual: 1, total: 7},
> track=M.

> [!FACT F-R2] src=meta.json:phase_history
> Raw calendar span (intake 2026-06-26 → learn 2026-07-12) is not a
> meaningful cycle-time signal here — the ticket crossed multiple
> separate work sessions with real-world gaps between them (e.g.
> `build:work` alone spans 2026-06-27 → 2026-07-11 in phase_history,
> but the actual build effort inside that span was a single continuous
> session). Do not compare this ticket's wall-clock span to the
> track-M median without excluding inter-session idle time.

> [!FACT F-R3] src=.klc/tickets/KLC-052/build-log.md
> `klc ack` was blocked once at `build:ack-needed` by the TDD-order
> gate (KLC-039): steps 1-5, 7, 8 had each been committed as a single
> test+impl commit instead of test-first-then-impl. Resolved by
> rewriting local (unpushed) branch history into proper RED-commit
> then GREEN-commit pairs per step — not by bypassing the gate.

> [!FACT F-R4] src=.klc/tickets/KLC-052/review-report.md
> Two independent review passes ran before merge: a codex external
> review (2 HIGH + 1 MEDIUM) and a fresh subagent review with no
> conversation context (1 HIGH + 2 LOW). All 3 HIGH findings were
> distinct (no overlap between the two passes) and were fixed with
> verified RED/GREEN cycles before merge.

> [!FACT F-R5] src=meta.json:rework_count
> `rework_count = {}` (the framework's own counter never incremented —
> all rework here was pre-ack, inside the build/review phases
> themselves, not a bounce-back from a later phase to an earlier one).

## What went well

- The phase_resolver + run_signal seam design (ADR-001) held up under
  two independent adversarial reviews with no design-level pushback —
  only an implementation bug and a prompt-wording bug were found, not
  a wrong architecture.
- TDD discipline was self-enforcing: the project's own TDD-order gate
  (KLC-039) caught that the build had drifted from red-before-green
  ordering, before it ever reached review. The fix was a clean git
  history rewrite (unpushed, so safe), not a gate bypass.
- The scope-expansion gate (`ack` / `scope_delta.compare`) correctly
  flagged real, legitimate scope growth (touching `intake`, `review`,
  `runner`, `tests`, and new `klc-plugin/commands`+`klc-plugin/skills`
  paths beyond the discovery-time module list) at three different
  points in the lifecycle (build, review, and again after the
  codex-driven `commands/run.md` fix) — each time correctly, not as
  false positives.
- Getting a second, *independent* review (no shared context with the
  implementer or the first reviewer) directly paid off: it found a
  HIGH bug (`agent_type` keyed on `phase_id` instead of `phase.prompt`'s
  stem) that both internal self-review and the codex pass missed,
  because every existing test happened to only exercise phase ids
  where the bug was invisible.

## What went wrong

- The bug above shipped past two review layers (self-review + codex)
  because no test in steps 1-8 ever resolved `phase_id` values where
  `phase_id != prompt-stem` (`build`, `acceptance-test-plan`,
  `detailed-test-plan`, `manual`, `learn`) — every test picked
  `design`/`discovery`/`xs-build`, where the bug was accidentally
  invisible. Test selection bias, not lack of testing.
- `SKILL.md`'s first draft of the interactive-gate step conflated two
  meaningfully different cases (mandatory clarify pass vs. an ordinary
  human-pick gate) under one "STOP" instruction, with the clarify
  action demoted to an "e.g." This is exactly the kind of ambiguity a
  prompt-driven (not code-driven) control-flow step is vulnerable to,
  and it was flagged by codex, not caught internally.
- `modules.json` was stale for this branch's new directories
  (`klc-plugin/commands`, `klc-plugin/skills`) — the scope-expansion
  gate's "unknown_files" bucket doesn't respond to `affected_modules`
  edits at all (it's computed purely from prefix-matching against
  `modules.json`), so the first two attempts to resolve a scope
  conflict by editing `affected_modules` alone didn't work; the index
  itself had to be corrected.

## Lessons (imperative)

- When a resolver/mapper claims to be "the one source of truth" for N
  categories, write a parametrized test over all N, not a test per
  category as they come up — partial coverage of a "single seam" is
  more dangerous than no seam, because it looks unified while quietly
  not being one.
- In a prompt-driven control-flow step, give each branch of a
  conditional its own explicit heading/bullet, never bury a mandatory
  action inside an "e.g." next to an optional one — treat prompt
  branches with the same rigor as code branches.
- When `ack`'s scope-expansion check reports `unknown_files`, don't
  just edit `meta.json:affected_modules` and retry — check whether the
  files are actually indexed in `modules.json` first; unindexed paths
  stay in `unknown_files` regardless of what `affected_modules` says.

## Proposed knowledge-base updates

- No `reviewer-allowlist.yml` changes proposed — the review findings
  were real bugs, not reviewer false-positives to suppress.
- Few-shot candidate for future orchestrator/resolver-style tickets
  (`core/agents/test-planner.md` or `core/agents/design.md`): "when a
  ticket introduces a function meant to be the single mapping across
  a fixed enumerable set (phase ids, track names, provider names),
  require a parametrized test iterating the *actual* enumeration from
  its source config, not a handful of representative cases."

## ADR

`design/adr.md` (ADR-001) accepted 2026-07-12 and promoted to
`docs/adr/ADR-001-phase-resolver-two-executors.md`. Two consequences
were revised inline against what actually happened (see the ADR's
`[revised]` notes) rather than left as unexamined predictions.

## Estimate accuracy

- estimate.total = 7 (M track). No `rework_count` bump recorded (all
  rework was pre-ack), so the estimate's rework-cost assumption was not
  tested by this ticket — the two review rounds' cost shows up as
  review-phase duration, not as a build-phase reopen.
