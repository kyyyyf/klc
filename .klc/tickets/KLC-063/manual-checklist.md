---
ticket: KLC-063
kind: manual-checklist
authority: human
---

# Manual checklist — KLC-063

`estimate.manual = 1`. The manual aspect — real multi-clone propagation and
real teardown/rollback behaviour — is exercised deterministically on a real
substrate (a bare `klc-state` origin, a real second clone, and real git hooks),
so each item below is backed by an automated real-repo test rather than a
hand-run two-machine walkthrough. All pass.

## Items

- [x] A second clone receives pre-existing `.klc/tickets` (state init commits &
      pushes them). (`test_state_init_commits_and_pushes_preserved_tickets`)
- [x] No empty commit is made when there is nothing to preserve.
      (`test_state_init_no_preserved_content_makes_no_empty_commit`)
- [x] Preserved-commit push failure is fail-safe: warn + exit 0, ticket committed
      locally. (`test_state_init_preserved_commit_pushfail_warns_exit0`)
- [x] Data-loss averted: a forced preserved-commit failure leaves the ticket on
      disk and exits cleanly (no traceback).
      (`test_state_init_preserved_commit_failure_preserves_tickets_no_crash`)
- [x] Derived files (`.lock`/`_prompt`/`.index.json`/`scratch/`/`tickets-index.jsonl`)
      never reach shared `klc-state`, for both NEW and already-TRACKED cases.
      (`..._excludes_derived_from_preserved_commit`, `..._converges_out_tracked_derived_on_upgrade`)
- [x] The repo-wide `.git/info/exclude` is left byte-identical.
      (`test_state_init_does_not_mutate_repo_exclude`)
- [x] A failed CAS push on an upgraded worktree leaves a clean index (unscoped
      rollback reset). (`test_upgraded_worktree_rollback_leaves_clean_index`)

## Verification note

All items run against a real bare-repo substrate with a real second clone and
real pre-receive / pre-commit hooks forcing the failure paths — stronger than a
manual walkthrough and repeatable as a regression gate. state/state_tx/klc057
sweep: 135 passed.
