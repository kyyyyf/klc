---
ticket: KLC-061
authority: hybrid
last_generated: 2026-07-16T09:35:00Z
---

# Test plan — KLC-061

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_ship_cas_pushes_advance_in_same_verb | feature ON (`.klc` is a `klc-state` worktree over a local bare origin); ticket at `<P>:ack-needed`; run `klc ship --pick N`; assert origin's `klc-state` shows `<P+1>:work` AND the released/acquired holder AFTER the single `klc ship` call — not riding a later push |
| AC-1 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_ship_routes_through_ack_and_next | assert ship delegates: holder of `<P>` released, holder of `<P+1>` acquired (the ack.run+next.run holder lifecycle), and Jira advanced exactly once per pushed transition |
| AC-2 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_steal_durable_on_origin | feature ON; holder stale; run `klc steal`; clone origin fresh and assert `meta.holder.id` == stealer on the ORIGIN branch, not only in the caller's worktree |
| AC-2 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_steal_staleness_evaluated_after_pull | seed a FRESH holder on origin but a STALE holder locally; `klc steal` must pull first and REFUSE (HolderActiveError) — staleness judged against pulled state, not stale local |
| AC-3 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_abort_cas_pushes_and_releases_holder | feature ON; ticket at `<X>:work` held by caller; `klc abort`; assert origin shows prev `<W>:ack`, superseded artefacts committed, and the aborted phase holder released — all in one CAS push |
| AC-3 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_jump_cas_pushes_and_acquires_holder | feature ON; ticket at `<X>:ack`; `klc jump <target> --yes`; assert origin shows `<target>:work`, budgets reset, target holder acquired, one CAS push |
| AC-3 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_jira_pull_wrapped_in_state_tx | feature ON; `klc jira reconcile pull --to <phase>` (stubbed Jira client); assert the `set_state` phase move is CAS-pushed and Jira fires only after the push |
| AC-3 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_jump_dryrun_and_jira_push_are_documented_noops | `klc jump <t>` (no --yes) and `klc jira reconcile push`/`jira status` write no klc tracked state and issue no CAS push — justified per-verb no-op |
| AC-4 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_jira_deferred_until_clean_cas_push | for ship/abort/jump/jira-pull with a Jira spy: assert Jira side-effect fires ONLY after the CAS push succeeds |
| AC-4 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_jira_discarded_on_rollback | stub `commit_and_push_cas_subtree` to reject; assert the deferred Jira push is DISCARDED (never fired) and never lands ahead of the klc advance reaching origin |
| AC-5 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_feature_off_ship_byte_identical | feature OFF (`.klc` plain dir); `klc ship` produces the same output + phase transition as today; no holder fields written; no git |
| AC-5 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_feature_off_steal_abort_jump_no_holder_or_git | feature OFF; steal/abort/jump complete with byte-identical behaviour; no holder writes, no pull/push; existing verb tests still pass |
| AC-6 | acceptance | tests/integration/test_klc057_fuzz_concurrent.py (EXTENDED: mods table + scenarios include `ship` and `steal`) | real OS processes, real bare origin, `multiprocessing.Barrier`; re-asserts the 7 invariants (no-wedge, no-deadlock, no-data-loss, holder-auth, legal-transitions, convergence, derived-never-shared) with ship/steal in the op mix |
| AC-6 | acceptance | tests/integration/test_klc061_wrap_verbs.py::test_steal_failed_cas_push_leaves_clean_state | REAL-SUBSTRATE (local bare repo, NOT a stub): force a CAS-push rejection on `klc steal`; assert holder unchanged, working tree + index clean, exit non-zero, no traceback |

## Edge cases

- `klc ship` where the ack step advances but the next step's CAS push is rejected: the ticket is left at a valid `<P>:ack` (first CAS push landed) and ship exits non-zero pointing at `klc next` — the two-transaction relaxation (C-004) must leave a coherent resting state, never a half-written phase.
- `klc ship` on a phase whose ack archives the ticket (`goto: archived`): ship must short-circuit after ack.run and NOT attempt next.run; exit 0 with `ARCHIVED`.
- `klc ship` on `:ack` or `:work` (not `:ack-needed`): must produce a clear error (finish work / already acked) with no state mutation — delegation must preserve these guards.
- `klc steal` racing a concurrent `heartbeat` that refreshes the holder on origin: after pull the holder is fresh → steal refuses (no cross-user takeover of a live holder).
- `klc steal` where the pull itself changes the ticket subtree (StaleStateError): steal exits non-zero with a re-run message; holder untouched.
- `klc abort` of a phase held by ANOTHER user (HolderConflictError): must refuse and surface the holder id, not silently release someone else's holder.
- `klc jump` backward that supersedes downstream artefacts: the moved files (under the ticket subtree) must be captured by the glob-commit and reach origin in the same CAS push as the phase move.
- Feature-OFF: every wrapped verb must skip holder writes entirely (gated on `if tx is not None:`) and touch no git.

## Regression scenarios

- All existing `tests/integration/test_klc057_*` (sequential + concurrent fuzz) continue to pass unchanged for intake/ack/next — the new wrapping must not perturb the already-wired verbs.
- Existing `ship`/`steal`/`abort`/`jump` unit/integration tests in feature-OFF mode produce byte-for-byte identical results (AC-5 catch-all).
- `tests/integration/test_gate_policy.py` (KLC-045) and the build-evidence gate remain green — ship's delegation to `ack.run` must still run gate-policy / scope checks that ack owns.
- The 7-invariant assertions in the fuzz harness stay who-wins-agnostic; adding ship/steal ops must not weaken any invariant.

## Detailed coverage
<!-- TBD — populated in phase 4 after Design -->

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
