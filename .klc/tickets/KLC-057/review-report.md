---
ticket: KLC-057
kind: review-report
authority: human
reviewed_by: general-purpose subagents (fresh, no context) + codex exec review --base main, across build + design-pass + 6 harden rounds + a fuzz/property gate
reviewed_at: 2026-07-16
review_depth: full
branch: feature/klc-057-wire-sync-holder
---

# Review report — KLC-057 (multi-user integration spine)

## Summary

KLC-057 wires `state_sync`(CAS) / `identity` / `holder` into `intake`/`ack`/`next`
via a `state_feature` detector + a self-healing `state_tx` transaction envelope,
so the multi-user primitives (KLC-053..056) become live behaviour — while
feature-OFF (single-user) stays byte-for-byte identical.

As the integration spine, it got the deepest review of the epic: a fresh
`general-purpose` subagent (per CLAUDE.md) + `codex exec review --base main` on
the initial build and after every fix round, then a design-pass when incremental
point-fixes stopped converging, then a **concurrency fuzz/property harness**
(sequential + true-multiprocess CAS-race drivers) as the systematic convergence
gate. Every finding from every source is closed; the fuzz is green.

## Verdict

APPROVED. Feature-on is data-safe for intake/ack/next (linearizable, wedge-free,
holder-authorized, jira-consistent, convergent — proven by the fuzz gate);
feature-off is byte-identical (AC-8). 743 tests pass.

## Finding classes found & closed (build → design-pass → harden1..6)

Incremental review found real issues one code-path at a time; when that stopped
converging, a **design-pass** re-cast `state_tx` as a self-contained, self-healing
envelope, and a **fuzz gate** then proved the classes closed. Closed classes:

- **Ordering (HIGH):** verbs mutated state before the tx pulled → dirty-tree
  pull crash + advance outside rollback. Fixed: lifecycle write moved INSIDE the
  tx (pull → mutate → push).
- **Deadlock (HIGH):** rollback / stray writes left the `.klc` worktree+index
  dirty → next pull wedged forever. Fixed: rollback resets tree AND index;
  derived caches (`tickets-index.jsonl`, `_prompt*`, `.index.json`, `.lock`,
  `scratch/`) are local/ignored; upgraded worktrees untracked at commit.
- **Data-loss (HIGH):** (a) self-heal first DISCARDED in-progress tracked
  artifacts — replaced with stash-around-pull (`pull_rebase_preserving`) that
  PRESERVES and pushes them, `StashConflictError` recoverable; (b) intake `--force`
  rmtree deleted a restored pre-existing ticket — gated on `created_new`.
- **Peer-clobber (HIGH):** intake could fast-forward-overwrite a peer ticket —
  post-pull taken-key re-check (`_KeyTakenError`).
- **Validate-before-pull (P1 class):** scope/gate/pick/`--force`/manual-completion
  validated pre-pull, applied post-pull → closed at the ENVELOPE level: `state_tx`
  captures the ticket subtree tree-hash before the pull and aborts
  (`StaleStateError`) if the pull changed it — so no verb path, current or future,
  can apply stale validation.
- **Holder-authorization (P1):** ack manual-completion, and `intake --force`,
  could move another user's held phase → both now refuse ("phase held by <id> —
  use `klc steal`") on the freshly-pulled holder.
- **Jira ordering (P1):** Jira advanced before the CAS push confirmed → deferred
  (`defer_jira_pushes`/`flush_jira_pushes`); Jira fires exactly once AFTER a
  successful push, discarded on rollback.

## Convergence evidence — the fuzz/property gate

`tests/integration/test_klc057_fuzz.py` (sequential) + `..._fuzz_concurrent.py`
(true multiprocess, barrier-forced CAS races). Seven invariants asserted after
every op: no-wedge, no-deadlock, no-data-loss, holder-authorization,
legal-transitions, convergence, derived-never-shared.

- Sequential: 5 seeds × 150 steps = **750 ops, 0 violations**.
- Concurrent (40-round soak): scenario1 (same-ticket ack race) `wins=40/losses=40`;
  scenario2 (same-key intake race) `intake_ok=40/taken=40`; scenario3
  (`--force` vs peer-held) `force_refused=40, steal_findings=0`; scenario4
  (mixed load) all invariants every round. **0 violations.**

The one invariant violation the concurrent harness ever found — the
`intake --force` holder-auth gap — was fixed (harden6) and its scenario flipped
from xfail to a passing invariant assertion.

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| AC-1 intake happy | PASS | `test_klc057_sync_holder`, real-repo, fuzz |
| AC-2 intake uniqueness (taken key, no artifacts) | PASS | `_KeyTakenError`; fuzz scenario2 |
| AC-3 intake acquires holder in same push | PASS | sync-holder tests |
| AC-4/5 ack releases holder, ordering/atomicity | PASS | real-repo, fuzz scenario1 (exactly-one-winner) |
| AC-6 next first-grab / refuse-steal | PASS | sync-holder + holder-conflict tests |
| AC-7 hidden on success | PASS | output-hygiene tests; terminal errors → clean messages |
| AC-8 feature-off byte-identical | PASS | feature-off parity tests; no git touched feature-off |
| AC-9 inside per-ticket lock | PASS | lock-scope tests (all three verbs) |
| AC-10 tests (local bare repo, no network) | PASS | all integration + fuzz use local bare repos |

## Deferred to follow-up (out of KLC-057 scope, documented in `.klc/wave1-followup-hardening.md`)

- **Sibling verbs `abort`/`jump`/`jira`** mutate tracked meta outside `state_tx`
  (feature-on their edits are preserved by the next verb's stash but not pushed by
  the mutating verb itself) — wrap them in `state_tx` for consistency.
- **Untracked-file / incoming-pull collision** (two writers add the identical
  brand-new untracked path) surfaces as a clean sync-failure, not a wedge, and is
  not auto-resolved. Rare (same-ticket single-writer).
- Optional hardening: reference the specific stash by ref in
  `pull_rebase_preserving` (currently relies on the lock + LIFO invariant, verified
  safe); strengthen the fuzz with more track-M/L coverage.

## Final state

`python3 -m pytest tests/ -q --ignore=tests/fixtures` → 743 passed, 12 skipped.
35 commits (build ×16, design-pass, harden1..6, fuzz ×2). Feature gated behind
`state_feature.enabled()` (klc-state worktree AND upstream); default single-user
KLC is unaffected and byte-identical.


---
[!CONFLICT] scope-expansion detected at review:ack-needed
  planned modules: ['intake', 'ack', 'core/phases', 'core/skills']
  actual modules:  ['ack', 'core/phases', 'core/skills', 'intake', 'tests']
  unplanned:       ['tests']
Resolve: update meta.json:affected_modules to include all touched modules, then re-run `klc ack KLC-057`.
