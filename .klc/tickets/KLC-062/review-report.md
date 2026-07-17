---
ticket: KLC-062
kind: review-report
authority: human
reviewed_by: general-purpose subagent (fresh, no context) + codex exec review --base main; findings aggregated, fix applied TDD
reviewed_at: 2026-07-16
review_depth: full
full_review_offered: true
branch: feature/klc-062-remind-read-only
---

# Review report — KLC-062 (klc remind truly read-only)

## Summary

KLC-062 makes `klc remind` truly read-only. `remind` runs on every
UserPromptSubmit and, via `can_complete_discovery → _sync_risk_tags`, rewrote
`meta.json` on every prompt — per-prompt churn. The fix threads a `persist` /
`persist_migration` flag from the entry points (`remind`, `status`,
`gate_policy`) through `can_complete*` down to `read_meta`, and adds
`read_meta_ro`, so the completion *decision* is unchanged while nothing is
written on the read-only path. The risk_tags sync and floor-guard audit are gated
to the persisting (ack) path.

Review model = "model B": a fresh non-fork `general-purpose` reviewer plus
`codex exec review --base main`; findings aggregated; fix applied TDD.

## Verdict

APPROVED. The single finding was a real bug (a missed write path), is fixed, and
is covered by a RED→GREEN byte-identical fixture. Targeted 45 tests pass; the
relevant regression band (278) passes; `scripts/klc` untouched.

## Findings — assessment (fix / won't-fix)

| # | Source | Severity | Finding | Assessment |
|---|--------|----------|---------|------------|
| F-1 | fresh HIGH + codex P2 (converged) | HIGH | The `persist` flag was threaded at the outer layer but **missed the `read_meta` call inside `can_complete_discovery`/`_lite`**, so a legacy-phase discovery ticket (`discovery-running`) was still migrated-and-written on the read-only path — the exact churn the ticket exists to remove. The pre-existing legacy test used an integrate-post fixture that routes to the generic checker (which never reads meta), so it never exercised the discovery read path. | **FIXED.** Thread `persist_migration` into both internal `read_meta` calls; add a `discovery-running` byte-identical fixture that fails on the old code and passes on the fix. RED→GREEN. |

No reviewer-allowlist changes: the finding was a real bug (a genuine missed
mutation site), not a false positive.

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| AC-1 `remind` writes nothing (meta.json byte-identical after run) | PASS | `test_remind_does_not_write_meta_for_completable_discovery`; discovery + legacy fixtures |
| AC-2 `status` read-only (no legacy-migration write) | PASS | `test_status_does_not_write_meta_legacy_phase` |
| AC-3 real `ack` still persists risk_tags (no regression) | PASS | AC-3 regression guard (step-3) |
| completion decision unchanged on the read-only path | PASS | probe returns identical (ok, advisory) with persist=False |

## Convergence note

An internal review with the wrong fixture (integrate-post) hid the exact bug the
ticket exists to fix. Both external reviewers caught it because they traced
*every* write path reachable from the entry point rather than validating against
the AC as written. Closing a "no-write" contract requires enumerating every
reachable mutation, not just the obvious top-level one.

## Final state

Merged `0644cfa` (PR #66), mirrored to origin; full suite green on main. The
read-only contract now holds for `remind` and `status`; the risk_tags/audit
writes remain on the ack path only.
