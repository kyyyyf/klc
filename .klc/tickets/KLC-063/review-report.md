---
ticket: KLC-063
kind: review-report
authority: human
reviewed_by: general-purpose subagent (fresh, no context) + codex exec review --base main; findings aggregated, fixes applied TDD across 3 fix rounds on the derived-handling class, each fix delta scoped-re-reviewed by codex
reviewed_at: 2026-07-16
review_depth: full
full_review_offered: true
branch: feature/klc-063-state-init-preserve-and-clean-rollback
---

# Review report — KLC-063 (state init preserves tickets + clean rollback index)

## Summary

KLC-063 does two things: (a) `state init` now commits pre-existing `.klc/tickets`
onto the `klc-state` branch (skip-empty, fail-safe push) so a second clone
receives them; and (b) `state_tx` rollback uses an unscoped `git reset` so a
failed CAS push on an upgraded worktree leaves a clean index. Full build/fix
detail (RED→GREEN per round, real-substrate proofs) is in `build-log.md`.

Review model = "model B": a fresh non-fork `general-purpose` reviewer plus
`codex exec review --base main`; findings aggregated; fixes applied TDD. This
ticket ran a bounded fix loop — **3 fix rounds on the derived-file-handling
class** — and each fix delta got a scoped codex re-review; the final re-review
came back clean.

## Verdict

APPROVED. Every finding was a real bug and every one is fixed with a
real-substrate (bare repo / real second clone / real hooks) RED→GREEN test. The
state/state_tx/klc057 sweep is 135 passed.

## Findings — assessment (fix / won't-fix)

| # | Source | Severity | Finding | Assessment |
|---|--------|----------|---------|------------|
| F-1 | codex P1 | HIGH (data-loss) | The failed preserved-commit ran **after** the backup was already deleted by `_merge_back`; a commit failure then tore down the merged worktree and crashed in `_restore_backup` — destroying the only copy of the preserved tickets. | **FIXED.** Keep the backup until the commit succeeds; drop it only after a fully-successful init; guard `_restore_backup` on `backup.exists()`. RED: `test_state_init_preserved_commit_failure_preserves_tickets_no_crash`. |
| F-2 | fresh HIGH | HIGH (INV7) | `git add -A` leaked derived files (`.lock`/`_prompt`/`.index.json`/`scratch/`/`tickets-index.jsonl`) into the shared `klc-state` branch. | **FIXED** (then hardened — see F-4). Applied the derived-ignore set before staging. RED: `test_state_init_excludes_derived_from_preserved_commit`. |
| F-3 | codex P2 (fix re-review) | MEDIUM ×2 | The F-2 fix (a) polluted the **shared** `.git/info/exclude` (a common git-dir file), silently hiding unrelated files in the user's main worktree; and (b) dropped the backup with `ignore_errors=True`, so a cleanup failure left `.klc.init-bak` behind with no warning, breaking the next init's preflight. | **FIXED.** Replaced `info/exclude` mutation with exclude **pathspecs** (`git add -A -- . :(exclude,glob)…`, no repo-wide side effect); replaced `ignore_errors=True` with a guarded rmtree that surfaces a leftover-path warning (init still exits 0). RED: `test_state_init_does_not_mutate_repo_exclude`, `test_state_init_backup_cleanup_failure_surfaces_warning`. |
| F-4 | codex P2 (3rd round) | MEDIUM | The exclude-pathspec `git add` stopped NEW derived files, but did **not** converge OUT a derived path the existing `klc-state` already TRACKS (legacy/upgrade layout) → init reported success with `.klc` dirty and the derived file still shared. | **FIXED — closed the class.** Stopped point-patching; matched the proven runtime discipline in `state_sync.commit_and_push_cas_subtree` (exclude NEW + `git rm --cached` TRACKED) by factoring `derived_untrack_pathspecs()` from the single `_DERIVED_IGNORES` source. Final scoped codex re-review: clean. RED: `test_state_init_converges_out_tracked_derived_on_upgrade`. |

No reviewer-allowlist changes: every finding was a real bug.

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| state init commits & pushes preserved tickets to `klc-state` | PASS | `test_state_init_commits_and_pushes_preserved_tickets` (real 2nd clone) |
| no empty commit when nothing to preserve | PASS | `test_state_init_no_preserved_content_makes_no_empty_commit` |
| preserved-commit push is fail-safe (warn + exit 0) | PASS | `test_state_init_preserved_commit_pushfail_warns_exit0` |
| data-loss averted on preserved-commit failure | PASS | `..._preserves_tickets_no_crash` (real pre-commit hook forces failure) |
| derived never shared into `klc-state` (new + tracked) | PASS | `..._excludes_derived_from_preserved_commit`, `..._converges_out_tracked_derived_on_upgrade` |
| repo-wide `.git/info/exclude` untouched | PASS | `..._does_not_mutate_repo_exclude` (byte-identical) |
| upgraded-worktree rollback leaves a clean index | PASS | `test_upgraded_worktree_rollback_leaves_clean_index` |

## Convergence note

The derived-handling class took 3 fix rounds (leaked → info/exclude pollution +
silent cleanup → already-tracked-not-converged) — a non-convergence signal. The
durable fix was to **stop point-patching and reuse the proven runtime
choke-point** (`commit_and_push_cas_subtree`'s derived discipline) rather than
re-invent staging in a bespoke `git add`. A fix can introduce regressions (the
round-1 derived fix caused 2 new P2s), so scoped re-review of the fix delta is
essential for delicate teardown/staging code.

## Note on pre-existing consistency advisories

`items validate` reports `D-004 refs=step-2,step-3` as `dangling_refs` and
`Q-001`/`Q-002` as `orphan_questions`. These are **benign and pre-existing**:
`D-004`'s `refs` uses the step-reference DECISION format (pointing at impl-plan
build steps, which are not indexed items) — the same format shipped KLC-052 uses
identically. They are advisory (validate returns exit 0) and not introduced by
this diff.

## Final state

Merged `89e1d5f` (PR #67), mirrored to origin; full suite green on main.
All fixes are covered by real-substrate tests (bare repo, real second clone, real
hooks); state/state_tx/klc057 sweep 135 passed.
