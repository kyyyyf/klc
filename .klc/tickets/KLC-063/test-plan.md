---
ticket: KLC-063
authority: hybrid
last_generated: 2026-07-16T00:00:00Z
---

# Test plan — KLC-063

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/integration/test_state_init.py::test_state_init_commits_and_pushes_preserved_tickets | Real bare-repo `origin`; after `klc state init` with a pre-existing `.klc/tickets/local.txt`, a **second fresh clone** of `origin` (or direct `git show origin/klc-state:tickets/local.txt`) receives the preserved ticket. Covers both the orphan-create and track-existing-origin paths. This is the real-substrate two-clone test (AC-6a). |
| AC-2 | acceptance | tests/integration/test_state_init.py::test_state_init_preserved_commit_pushfail_warns_exit0 ; ::test_state_init_no_preserved_content_makes_no_empty_commit | Push failure after a successful preserved-commit warns "committed locally but not pushed" and exits 0 (mirrors the orphan-push warn path); nothing-to-preserve / no-tracked-change makes no empty commit and leaves today's output+exit code unchanged. |
| AC-3 | acceptance | tests/integration/test_klc057_hardening.py::test_upgraded_worktree_rollback_leaves_clean_index | Real `.klc/` worktree that TRACKS `knowledge/tickets-index.jsonl` (upgraded layout); a forced CAS push failure drives the `state_tx` rollback; assert `git status --porcelain` shows **no** staged `D knowledge/tickets-index.jsonl` (clean index) and the on-disk file is untouched. This is the real-substrate upgraded-worktree rollback test (AC-6b). |
| AC-4 | acceptance | tests/integration/test_klc057_hardening.py::test_orphan_worktree_rollback_still_clean_index (regression) ; existing ::test_* rollback suite | On a KLC-053-created orphan (derived index never tracked) a forced push failure still rolls back to a clean tree AND clean index (the fix is a no-op); an unscoped index reset does not disturb another ticket's stash-popped working-tree edits. |
| AC-5 | acceptance | tests/test_state_tx.py::test_noop_when_feature_off (existing) ; full existing state suite (test_state_tx.py, test_state_sync.py, test_state_init.py, test_klc057_*) | Feature-OFF `state_tx` stays a pure pass-through (no git); every existing intake/ack/next and state test still passes after the change. |
| AC-6 | acceptance | AC-6a → the AC-1 two-clone test above; AC-6b → the AC-3 upgraded-worktree test above | Real git substrate only (local bare-repo upstream + a real second clone / tracked-index worktree) — no stubbed git, per the KLC-057 lesson. Both listed explicitly so the "real-substrate" requirement is a first-class coverage row, not an afterthought. |

## Edge cases

- **Nothing to preserve**: `.klc/` absent or empty at init → no `_merge_back` content → no commit, no push, output unchanged (AC-2).
- **Merge produced no tracked change**: preserved content is byte-identical to what the branch already carries → the new commit step must detect "nothing to commit" and not create an empty commit (AC-2).
- **Preserved commit OK, push fails** (offline / auth / permission) → warn-and-continue, exit 0, backup already consumed but data is committed locally so nothing is stranded (AC-2, C-001).
- **Preserved commit step itself fails** (e.g. commit hook) → must fall into the existing `except` → `_teardown_partial` + `_restore_backup`, so the user's `.klc.init-bak` is restored (C-001).
- **Upgraded worktree, `knowledge/tickets-index.jsonl` tracked, push fails** → staged top-level deletion must be cleared by rollback (AC-3).
- **Orphan worktree, derived index never tracked, push fails** → `rm --cached --ignore-unmatch` staged nothing → rollback is a no-op there; must stay clean (AC-4).
- **Other-ticket dirty edit present during a failed tx** → stash-popped edit lives in the working tree; an unscoped `git reset -q` (index-only, no `--hard`) must not destroy it (AC-4, C-003).
- **Feature OFF** → the rollback line is never reached; pass-through unchanged (AC-5).

## Regression scenarios

- **core/phases (state init)**: the full existing `test_state_init.py` suite (idempotency, offline-refuse, wrong-branch reject, backup-stranded refuse, symlink/dir-vs-file merge, orphan-push warn) must stay green — the new commit step is added inside the existing try/except and must not perturb them.
- **core/skills (state_tx / state_sync)**: `test_state_tx.py`, `test_state_sync.py`, `test_klc057_hardening.py`, `test_klc057_real_repo.py`, `test_klc057_sync_holder.py`, `test_klc057_fuzz*.py` — the rollback change must not regress the clean-tree-after-every-op soak or the stale-abort / preserve-uncommitted / other-ticket-safety tests.
- **Feature-OFF intake/ack/next**: existing verb tests unchanged (AC-5).

## Manual checklist (populated iff estimate.manual ≥ 2)
<!-- estimate.manual = 1 (fully autotestable via bare-repo + second-clone fixtures); no manual checklist required. -->

## Detailed coverage
<!-- TBD — populated in phase 4 (detailed mode) after Design, as per-step **Tests:** blocks in impl-plan.md (M-track). -->

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
