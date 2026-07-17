---
ticket: KLC-061
kind: review-report
authority: human
reviewed_by: general-purpose subagent (fresh, no context) + codex exec review --base main; findings aggregated, fixes applied TDD, delicate fix delta re-reviewed by codex
reviewed_at: 2026-07-16
review_depth: full
full_review_offered: true
branch: feature/klc-061-wrap-forward-holder-verbs
---

# Review report — KLC-061 (wrap forward/holder verbs in state_tx)

## Summary

KLC-061 wraps the state-mutating verbs that shipped before the KLC-057 envelope —
`ship`, `steal`, `abort`, `jump`, and `jira` reconcile — in the
`acquire_lock → state_tx → holder` envelope, so they behave like `intake`/`ack`/
`next` (CAS-push + holder-auth + deferred-Jira). `ship` delegates to `ack.run`
(+`next.run` if still `:ack`); the old `ship` was already broken because
`apply_ack` auto-advances and the second advance errored (ADR D-002).

Review model = "model B": a fresh non-fork `general-purpose` reviewer plus
`codex exec review --base main` on the branch; findings aggregated; fixes applied
TDD; the delicate holder-liveness fix got a scoped codex re-review of the fix
delta (clean). Two independent reviewers with different biases found
non-overlapping real gaps (codex: holder-auth; fresh: lock).

## Verdict

APPROVED. Every finding was a real bug and every one is fixed and covered by a
RED→GREEN test. Feature-ON, the wrapped verbs are now lock-scoped,
holder-authorized, CAS-pushed, and Jira-deferred; feature-OFF is byte-identical.
23 targeted tests pass; the concurrency fuzz (scenarios 5/6 added) shows 0
invariant violations; full regression 762 passed.

## Findings — assessment (fix / won't-fix)

| # | Source | Severity | Finding | Assessment |
|---|--------|----------|---------|------------|
| F-1 | codex P2 + fresh MEDIUM (converged) | HIGH | `jira reconcile` pull/force-pull got the `state_tx` envelope but not the per-ticket **lock** nor **holder-auth** — it could move a ticket held by another user. | **FIXED.** Added `acquire_lock` + `acquire_holder`: refuses a ticket held by another user (→ rollback), claims it for the caller on success, leaves no stale holder. RED→GREEN: `test_jira_pull_refuses_ticket_held_by_another_user`. |
| F-2 | codex P2 (surfaced on the F-1 fix re-review) | MEDIUM | A stale **same-user** holder was not refreshed on pull/jump, so an active holder was immediately stealable. | **FIXED.** Refresh liveness via `heartbeat_holder` (KLC-061 is its first production caller) in `pull` + `jump`. Scoped codex re-review of the fix delta: clean. |
| F-3 | fresh LOW | LOW | Stale `jira.py` module docstring; abort/jump deferred-Jira timing under-tested. | **FIXED.** Docstring updated; added abort/jump deferred-Jira timing tests. |
| Q-002 | design-pass | — (descope) | `jira sync --apply` / `meta.jira_sync` not wrapped in `state_tx`. | **WON'T FIX (ratified descope → KLC-065).** This path is advisory drift-tracking, not lifecycle state; wrapping it is out of KLC-061's "lifecycle-state verbs" scope. Tracked as follow-up KLC-065. |

No reviewer-allowlist changes: every finding above was a real bug (the only
non-fix is a deliberately-ratified descope, not a false positive).

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| ship/steal/abort/jump/jira run inside `acquire_lock → state_tx → holder` | PASS | `test_klc061_wrap_verbs.py` (23) |
| holder-auth: refuse a ticket held by another user (rollback) | PASS | `test_jira_pull_refuses_ticket_held_by_another_user` |
| stale same-user holder refreshed on activity (pull/jump) | PASS | heartbeat-refresh tests |
| deferred-Jira fires once after a clean CAS push (abort/jump) | PASS | abort/jump deferred-Jira timing tests |
| concurrency safety under stale-steal / ship-vs-ack | PASS | fuzz scenarios 5/6, 0 invariant violations |
| feature-OFF byte-parity | PASS | verb-regression suite unchanged |

## Convergence note

Wrapping many scattered verbs one at a time surfaces companion-guard gaps: the
envelope alone is not enough — lock + holder-auth + Jira-defer must all move
together for each verb. Two independent reviewers found non-overlapping gaps,
which is signal (keep two review sources for cross-cutting infra). The
holder-liveness-refresh-on-activity concern is cross-cutting (`jump` shares it)
and points to KLC-064.

## Final state

Merged `f833d5a` (PR #65), mirrored to origin; full suite green on main
(762 passed). Feature gated behind `state_feature.enabled()`; default single-user
KLC is byte-identical.


---
[!CONFLICT] scope-expansion detected at review:ack-needed
  planned modules: ['ack', 'core/phases', 'core/skills', 'tests']
  actual modules:  ['CLAUDE']
  unplanned:       ['CLAUDE']
Resolve: update meta.json:affected_modules to include all touched modules, then re-run `klc ack KLC-061`.
