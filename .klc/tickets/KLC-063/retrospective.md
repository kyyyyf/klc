---
ticket: KLC-063
authority: human
last_generated: 2026-07-17T00:00:00Z
---

# Retrospective — KLC-063

## What happened (facts, not opinions)

> [!FACT F-R1] src=meta.json:estimate
> estimate = {complexity:2, uncertainty:1, risk:2, manual:1, total:6}, track=M,
> risk_tags=[data, migration]. Two changes: state init commits pre-existing
> `.klc/tickets` onto `klc-state` (so a second clone receives them), and
> `state_tx` rollback uses an unscoped `git reset` for a clean index on an
> upgraded worktree.

> [!FACT F-R2] src=build-log.md, review-report.md
> The derived-file-handling class took **3 fix rounds**: (1) `git add -A` leaked
> derived files into shared `klc-state`; (2) the fix for that polluted the shared
> `.git/info/exclude` and silently swallowed a backup-cleanup failure; (3) the
> exclude-pathspec fix still did not converge OUT a derived path the existing
> `klc-state` already tracked (upgrade layout).

> [!FACT F-R3] src=build-log.md
> A separate P1 (codex) was pure data-loss: the preserved-commit ran after the
> backup was deleted, so a commit failure destroyed the only copy and crashed in
> teardown. Fixed by keeping the backup until the commit succeeds.

> [!FACT F-R4] src=build-log.md
> Every fix has a real-substrate RED→GREEN test (bare repo, real second clone,
> real hooks forcing the failure paths). state/state_tx/klc057 sweep 135 passed.
> Merged `89e1d5f` (PR #67).

## What went well

- **The class was finally closed by reuse, not another patch.** After three
  point-fixes on derived handling, the durable fix was to match the proven
  runtime discipline already in `state_sync.commit_and_push_cas_subtree` (exclude
  NEW + `git rm --cached` TRACKED), factored from the single `_DERIVED_IGNORES`
  source of truth — one choke-point instead of a fourth bespoke staging path.
- **Scoped re-review of each fix delta caught fix-introduced regressions.** The
  round-1 derived fix itself introduced 2 new P2s (info/exclude pollution, silent
  cleanup failure); re-reviewing only the fix delta surfaced them before merge.
- **Real-substrate tests made the data-loss and rollback paths observable.** A
  real pre-commit hook forcing the preserved-commit to fail proved the ticket
  survives on disk and init exits cleanly.

## What went wrong

- **Point-patching the derived-handling class did not converge.** Three rounds of
  "fix the next leaked case" is itself the signal that the fix was at the wrong
  altitude — the bespoke `git add` re-invented staging that the runtime already
  did correctly elsewhere.
- **A fix introduced fresh regressions.** The first derived fix reached for the
  nearest tool (`ensure_derived_ignored` → `info/exclude`) which had a shared,
  repo-wide side effect — a fix that made a new mess in delicate teardown code.

## Lessons (imperative)

- When a fix keeps finding the *next instance of the same class* (here: 3 rounds
  of leaked-derived), STOP patching instances and close the class at a single
  choke-point — prefer reusing an already-proven runtime discipline over
  re-inventing it in a bespoke code path.
- For delicate teardown / staging / rollback code, always **scoped-re-review the
  fix delta itself** — a fix here is as likely to introduce a regression as to
  remove one (round-1 fix → 2 new P2s).
- Never delete the only backup before the operation that depends on it has
  succeeded; keep it until success and guard the restore path.

## Proposed knowledge-base updates

- Few-shot for `core/agents/review/*`: "when a diff stages files for a shared
  branch, check it reuses the project's single derived-ignore discipline (exclude
  NEW + untrack TRACKED) rather than a bespoke `git add`; a bespoke stager will
  leak derived files or mutate shared git-dir state."
- No `reviewer-allowlist.yml` changes — every finding was a real bug.

## Estimate accuracy

- estimate.total = 6 (M). Build effort matched ~M, but the fix effort ran over: a
  3-round derived-handling class plus a data-loss P1, each needing a
  real-substrate reproducer. Consistent with the epic-wide signal that
  state/`state_tx`/teardown coordination work carries a review-and-harden tail the
  estimate model under-weights — a risk-based floor should flag "touches
  state_tx / teardown / shared-branch staging".
