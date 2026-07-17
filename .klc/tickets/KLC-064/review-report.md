---
ticket: KLC-064
kind: review-report
authority: human
reviewed_by: general-purpose subagent (fresh, no context) + codex exec review --base main; findings aggregated, fixes applied TDD
reviewed_at: 2026-07-16
review_depth: full
full_review_offered: true
branch: feature/klc-064-wire-heartbeat
---

# Review report — KLC-064 (wire heartbeat_holder, feature-ON, throttled)

## Summary

KLC-064 gives `heartbeat_holder` (KLC-058) its first production caller, so
`steal_holder`'s TTL steal-safety stops being inert. A new `klc heartbeat` verb +
UserPromptSubmit hook refreshes `heartbeat_at` for held `:work` tickets and
CAS-pushes via KLC-061's `state_tx` holder envelope, throttled to ≤1 push per
`HOLDER_TTL_SECONDS // 3`; within the window it is a read-only no-op
(`read_meta_ro`, KLC-062 no-churn). Feature-OFF it is a hard no-op. The ticket was
re-scoped S→M at design-pass (see the convergence note).

Review model = "model B": a fresh non-fork `general-purpose` reviewer plus
`codex exec review --base main`; findings aggregated; fixes applied TDD.

## Verdict

APPROVED. The concurrency design was confirmed sound by the fresh reviewer (no
HIGH/MEDIUM); the one P2 (codex) and two LOWs (fresh) are fixed and covered.
`test_heartbeat.py` 15 passed; the real bare-repo two-worktree steal-vs-heartbeat
race is coherent and stable at 40 rounds; full regression 812 passed;
feature-OFF byte-parity holds.

## Findings — assessment (fix / won't-fix)

| # | Source | Severity | Finding | Assessment |
|---|--------|----------|---------|------------|
| — | fresh | (none) | Concurrency design reviewed and confirmed sound: the throttle marker reflects origin state; the race guard is doubly-safe (pull `StaleStateError` + in-body ownership recheck); CAS guarantees a single winner. | No change needed — recorded as a positive finding. |
| F-1 | codex P2 | MEDIUM | The heartbeat scan aborted entirely if one held ticket's `acquire_lock` raised, so every later held ticket went unrefreshed in that run. | **FIXED.** Per-ticket `try/except: continue` — one ticket's lock failure no longer starves the rest. RED→GREEN. |
| F-2 | fresh LOW | LOW | A docstring claimed the load-bearing `except` catches `NothingToCommitError`, but it actually catches `StaleStateError` — misleading for the next maintainer. | **FIXED.** Docstring reworded to name the exception actually caught. |
| F-3 | fresh LOW | LOW | `os.getcwd()` was called outside the `try`, so a deleted cwd could crash the advisory instead of exiting 0. | **FIXED.** Moved `os.getcwd()` inside the `try` — a deleted cwd still exits 0. |

No reviewer-allowlist changes: every finding was a real issue (and the fresh
reviewer's design confirmation was a genuine positive, not a suppressed finding).

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| feature-ON: first push advances `heartbeat_at` at origin | PASS | `test_feature_on_first_push_advances_heartbeat_at_at_origin` |
| an active holder on a long phase is not stealable | PASS | `test_long_hold_active_holder_not_stealable` |
| within-window run is a read-only no-op (KLC-062 no-churn) | PASS | `test_within_window_is_readonly_noop` |
| hook is best-effort (exits 0 on child failure) | PASS | `test_hook_exits_0_on_child_failure`, `test_advisory_never_crashes_exits_0` |
| feature-OFF byte-identical meta | PASS | `test_feature_off_meta_byte_identical` |
| steal-vs-heartbeat coherence over interleavings | PASS | `test_steal_vs_heartbeat_coherence_over_interleavings` (real bare-repo, 40 rounds) |
| one ticket's lock failure does not starve later held tickets | PASS | per-ticket try/except test |

## Convergence note

The FIRST design (S, feature-OFF, write-every-prompt) was sent back at
design-pass because a heartbeat's value is entirely multi-user (feature-OFF it is
worthless) and a write-every-prompt shape reintroduces the exact churn KLC-062
removes. The accepted shape — `heartbeat_at` doubling as the throttle
"last-pushed" marker, window = `TTL/3`, read-only within the window, write+push
through the KLC-061 envelope — is the clean fix. This is a track-estimate signal:
the work looked like S wiring but was M coordination (touches `state_tx` + a real
steal-race).

## Final state

Merged `8414526` (PR #68), mirrored to origin; full suite green on main
(812 passed). Feature gated behind `state_feature.enabled()`; default single-user
KLC is byte-identical.
