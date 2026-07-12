---
ticket: KLC-056
kind: review-report
authority: human
reviewed_by: general-purpose subagent (fresh, no conversation context) + codex exec review --base main
reviewed_at: 2026-07-12
review_depth: full
branch: feature/klc-056-holder
---

# Review report — KLC-056

## Summary

Two independent reviews ran against this branch: a fresh `general-purpose`
subagent (no conversation context, per CLAUDE.md's mandatory pre-review-report
step — no dedicated `code-reviewer` agent type exists in this environment) and
`codex exec review --base main`. Both confirmed all 8 ACs satisfied and the
14-test suite green. They agreed on one substantive point at different
severities; per the operator's decision ("fix all findings including LOW") it
was fixed with a RED→GREEN cycle.

## Verdict

APPROVED — all findings resolved; 20 tests pass (14 original + 6 review-fix).

## Findings and assessments

### V1 — codex P2 / fresh LOW-2 — malformed existing holder not validated (fixed)

Both reviewers flagged the same code: `acquire_holder`/`release_holder` used
`if existing:` to decide whether a holder was present. An empty-dict holder
(`{}`) is falsy, so it was treated as a free phase and silently overwritten;
a same-id holder missing `machine` was returned as a valid idempotent acquire.
codex graded this P2 (the test-plan calls out malformed records as needing
`ValueError`); the fresh reviewer graded it LOW (meta is normally well-formed,
and AC-8 concerns the *input* identity, which is validated).

**Fix (applied):** added `_existing_holder(meta)` which fails closed — a free
phase is ONLY an absent or explicitly-`null` holder; any other value (empty
dict, non-dict, or a dict with missing/empty `id`/`machine`/`since`) raises
`ValueError` rather than being overwritten or returned as valid. Both
functions now route through it. RED commit `b97cf85` (5 malformed-holder tests
+ 1 non-clobber test, all failing), GREEN commit `9fa592c`.

### V2 — fresh LOW-1 — no explicit non-clobber assertion (fixed)

The test suite never asserted that sibling meta keys survive an acquire/release
(the code was correct, but a regression dropping them wouldn't be caught).

**Fix (applied):** `test_acquire_release_preserve_sibling_meta_keys` asserts
`ticket`/`phase`/`phase_history` are untouched across both operations. In the
same RED commit `b97cf85`.

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| AC-1 | PASS | `acquire_holder` absent/null → writes+returns; `test_ac1_*` |
| AC-2 | PASS | different id → `HolderConflictError(holder=existing)`; `test_ac2_*` |
| AC-3 | PASS | same id idempotent, `since` preserved; `test_ac3_*` |
| AC-4 | PASS | `release_holder` by holder → None, True; `test_ac4_*` |
| AC-5 | PASS | different id → raises, unchanged; `test_ac5_*` |
| AC-6 | PASS | null/absent → False no-op; `test_ac6_*` |
| AC-7 | PASS | no fs/git I/O; `test_ac7_no_fs_or_git_io` (spies open/run/Popen) |
| AC-8 | PASS | identity shape + ISO-8601 Z `since`; `test_ac8_*` |

## Final state

`python3 -m pytest tests/test_holder.py -q` → 20 passed. holder.py performs no
filesystem or git I/O (delegates to `lifecycle.read_meta`/`write_meta`); import
convention copied from `gate_policy.py`.
