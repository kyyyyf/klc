---
ticket: KLC-064
kind: manual-checklist
authority: human
---

# Manual checklist — KLC-064

`estimate.manual = 1`. The manual aspect — real multi-user steal-vs-heartbeat
behaviour and the no-churn throttle — is exercised deterministically by a real
bare-repo two-worktree CAS-race test plus byte-identical no-churn fixtures, so
each item is backed by an automated check rather than a two-machine walkthrough.
All pass.

## Items

- [x] feature-ON: the first heartbeat advances `heartbeat_at` at origin.
      (`test_feature_on_first_push_advances_heartbeat_at_at_origin`)
- [x] an active holder on a long phase is NOT stealable (TTL steal-safety now
      live). (`test_long_hold_active_holder_not_stealable`)
- [x] within the throttle window the run is a read-only no-op — no meta churn
      (KLC-062). (`test_within_window_is_readonly_noop`)
- [x] the UserPromptSubmit hook is best-effort: exits 0 on child failure and
      never crashes the prompt. (`test_hook_exits_0_on_child_failure`,
      `test_advisory_never_crashes_exits_0`)
- [x] feature-OFF: `meta.json` byte-identical (hard no-op).
      (`test_feature_off_meta_byte_identical`)
- [x] steal-vs-heartbeat coherence over interleavings on a real bare repo — both
      winners legal, full coherence invariant, stable at 40 rounds.
      (`test_steal_vs_heartbeat_coherence_over_interleavings`)
- [x] one held ticket's `acquire_lock` failure does not starve later held
      tickets (per-ticket try/except). (per-ticket try/except test)

## Verification note

The real bare-repo two-worktree CAS race exercises exactly the multi-user
coordination that a manual smoke would target, but deterministically and
repeatably (40-round soak). A live two-operator smoke can still be run ad hoc
before enabling the feature in a shared repo.
