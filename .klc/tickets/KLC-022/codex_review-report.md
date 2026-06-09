---
ticket: KLC-022
phase: review
authority: codex
verdict: CHANGES REQUESTED
reviewed_at: 2026-06-09
---

# KLC-022 codex review report

## Summary

CHANGES REQUESTED. The pull implementation compiles and the current tests pass,
but this review found blocking repository-state, behavior, and coverage issues
against `.klc/tickets/KLC-022/spec.md`.

ISSUES_TOTAL=9 ISSUES_BLOCKING=7

---

## Blocking Issues

### [CRITICAL] `core/skills/jira_sync.py` is still unmerged in the Git index - core/skills/jira_sync.py:1

`git status --short` reports `UU core/skills/jira_sync.py`, and
`git ls-files -u` still contains stages 1/2/3 for that path. The working file
has no visible conflict markers and compiles, but the repository cannot be
committed or reviewed as a resolved change until the index is fixed.

Fix: resolve the merge state explicitly by staging the intended
`core/skills/jira_sync.py` content after verifying it is the desired combined
version.

### [HIGH] Backward pull supersedes the target phase itself - core/skills/jira_sync.py:938

`_backward_pull()` computes `phases_to_supersede = track_ids[tgt_idx: cur_idx + 1]`.
For a pull from `review` back to `build`, this supersedes both `build` and
`review`. AC-4 says backward pull supersedes downstream artefacts; the target
phase is not downstream of itself. Including the target can move the target
phase's own artefacts out of the live ticket and then set the ticket to
`build:work`, leaving the rework target without its current inputs/context.

Fix: supersede phases after the target through the current phase, for example
`track_ids[tgt_idx + 1: cur_idx + 1]`, and add a regression test asserting the
target phase is not superseded.

### [HIGH] CLI backward pull does not require confirmation before superseding - core/phases/jira.py:197

AC-4 requires confirmation before backward pull supersedes downstream artefacts.
`_reconcile_pull()` has a placeholder check, but it always falls through to
`jira_sync.pull()`. In non-TTY or unconfirmed CLI usage, a backward pull can
supersede artefacts immediately.

Fix: determine direction before calling `pull()`. For backward non-force pulls,
abort in non-TTY and require explicit confirmation in TTY before calling the
state-changing implementation.

### [HIGH] Conditional forward skips are not recorded as `event=skipped` - core/skills/jira_sync.py:897

AC-3 says forward pull must respect conditional skips, with condition-false
steps recorded as skipped. `_forward_pull()` only appends the phase id to the
final `jira-pull` event's `skipped_phases` array; it does not write structured
`phase_history` entries with `event: skipped` for each skipped phase. This loses
the same audit trail that normal `advance_to_next()` produces.

Fix: reuse or expose lifecycle skip recording for each condition-false phase, or
write equivalent structured skipped events before the final `jira_pull()` event.

### [HIGH] `jira_pull()` can trigger legacy Jira push during pull - core/skills/lifecycle.py:402

`jira_pull()` calls `set_state()`, and `set_state()` always calls
`_jira_push_after_state()`. For `event="jira-pull"` or
`event="jira-force-pull"`, `_jira_push_after_state()` treats the source as a
non-managed decision point and dispatches legacy `jira_sync.push_phase()` when
legacy sync is enabled. Pull is supposed to move klc to Jira, not initiate an
extra klc-to-Jira push from the pull state write.

Fix: suppress Jira push dispatch for `jira-pull` and `jira-force-pull` events,
or add a low-level state writer path for Jira pull that records provenance
without invoking post-state push hooks.

### [HIGH] Forward conditional-skip test does not test a forward pull - tests/integration/test_jira_pull.py:152

`test_forward_pull_skips_conditional_phases()` starts at `integrate:ack` and
calls `pull(..., "review")`. On the S track, `review` is earlier than
`integrate`, so this is a backward pull, not a forward pull through conditional
steps. The assertion allows `"pulled"`, `"stopped"`, or `"noop"` and never
checks `skipped_phases` or `phase_history`, so the AC-3 skipped-event defect is
not covered.

Fix: construct a ticket before the conditional phase and pull to a later target
that crosses a condition-false phase; assert both `skipped_phases` and
`phase_history` skipped events.

### [HIGH] CLI and inline rework fork coverage is incomplete - tests/integration/test_jira_pull.py:330

The test main list covers direct `jira_sync.pull()` / `_pull_impl()` calls and
basic lifecycle event writing, but it does not cover `klc jira reconcile pull`,
`force-pull`, backward non-TTY abort/confirmation, missing-input CLI output, or
the AC-7 inline rework fork in `_prompt_conflict()`. These are user-facing and
state-changing contracts from AC-2, AC-4, AC-6, AC-7, and AC-8.

Fix: add integration tests for the CLI subcommands and prompt branch, including
backward confirmation, non-TTY rejection, valid candidate selection, invalid
candidate handling, and force-pull `--reason` audit fields.

---

## Non-Blocking Issues

### [MEDIUM] `force-pull --reason` is optional despite audit contract - core/phases/jira.py:168

AC-6 defines `force-pull --to <phase> --reason "..."` and requires the reason
to be written into the structured audit event. The CLI currently defaults
`--reason` to an empty string, so a forced state movement can be recorded
without a human-readable reason.

Fix: make `--reason` required for `force-pull`, or reject empty values before
calling `jira_sync.pull(..., force=True)`.

### [MEDIUM] Pull semantics are not documented beyond command names - docs/process.md:390

The docs list `pull` and `force-pull` commands, but they do not explain the
KLC-022 semantics: explicit `--to`, Jira status candidate validation,
forward-vs-backward direction, missing inputs versus conditional skips,
backward supersede confirmation, or force-pull audit fields.

Fix: add a KLC-022 section covering pull/force-pull behavior and the safety
rules a user must understand before moving klc state from Jira.

---

## Verification Run

These checks were run during review:

- `python3 -m py_compile core/skills/jira_sync.py core/skills/lifecycle.py core/phases/jira.py tests/integration/test_jira_pull.py` - PASS
- `python3 tests/integration/test_jira_pull.py` - PASS
- `python3 tests/integration/test_jira_managed.py` - PASS
- `python3 tests/e2e_pipeline.py` - PASS
- `python3 core/phases/doctor.py` - PASS
- `git diff --check -- core/skills/jira_sync.py core/skills/lifecycle.py core/phases/jira.py tests/integration/test_jira_pull.py docs/process.md` - PASS
- `git ls-files -u` - FAIL: `core/skills/jira_sync.py` remains unmerged

## Verdict

**CHANGES REQUESTED** - blocking issues remain. Because this file is the
Codex-prefixed review artefact, the standard ack command may still expect the
normal review output path if the lifecycle is advanced by tooling.
