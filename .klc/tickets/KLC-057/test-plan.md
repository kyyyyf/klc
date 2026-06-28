---
ticket: KLC-057
authority: hybrid
last_generated: 2026-06-27T09:00:00Z
---

# Test plan — KLC-057

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/integration/test_klc057_sync_holder.py::test_intake_happy_path_cas_push_succeeds | feature on (`.klc` is a `klc-state` worktree); key free; verifies INTAKE_OK + exit 0 |
| AC-2 | acceptance | tests/integration/test_klc057_sync_holder.py::test_intake_taken_key_rejected_no_artifacts | key held by peer; CAS push rejects; verifies no meta.json, no index entry, non-zero exit, message names key |
| AC-3 | acceptance | tests/integration/test_klc057_sync_holder.py::test_intake_acquires_holder_in_same_cas_push | builds on AC-1; reads meta.json after intake; holder == git config user.email; same push carried both create + holder |
| AC-4 | acceptance | tests/integration/test_klc057_sync_holder.py::test_ack_releases_holder_on_forward_transition | user holds phase P; klc ack advances to P+1; meta.json holder for P is cleared; CAS-pushed atomically |
| AC-5 | acceptance | tests/integration/test_klc057_sync_holder.py::test_ack_cas_rejected_does_not_advance_remote_phase | CAS push is stubbed to reject; ack exits non-zero with concurrent-update message; remote phase is unchanged (no forward advance on the remote) |
| AC-6a | acceptance | tests/integration/test_klc057_sync_holder.py::test_next_first_grabs_free_phase | ticket at P:ack, P+1 free; klc next advances to P+1:work and sets holder to current user; CAS-pushed |
| AC-6b | acceptance | tests/integration/test_klc057_sync_holder.py::test_next_refuses_to_steal_held_phase | P+1 already held by another user; klc next exits non-zero with "held by" message; holder is unchanged |
| AC-7 | acceptance | tests/integration/test_klc057_sync_holder.py::test_success_path_output_contains_no_git_internals | collects stdout of AC-1 + AC-4 + AC-6a runs; asserts no occurrence of: "state-repo", "clone", "remote", "pull_rebase", "commit_and_push", "klc-state" |
| AC-8a | acceptance | tests/integration/test_klc057_sync_holder.py::test_feature_off_intake_behavior_identical | no klc-state remote configured; intake produces same output and artifacts as pre-KLC-057 baseline |
| AC-8b | acceptance | tests/integration/test_klc057_sync_holder.py::test_feature_off_ack_next_no_holder_fields | no klc-state remote; ack and next complete; meta.json contains no holder fields |
| AC-9 | acceptance | tests/integration/test_klc057_sync_holder.py::test_sync_runs_inside_per_ticket_lock | concurrent klc ack on same ticket is serialised by the per-ticket lock; the second caller does not interleave with remote sync of the first |
| AC-10 | acceptance | tests/integration/test_klc057_sync_holder.py (full file, all scenarios) | the file is the test-suite AC-10 mandates; uses bare-repo or stubbed state_sync fixture — no network |

## Edge cases

- CAS push rejected (non-fast-forward) during `intake` — local rollback must remove `meta.json`, `raw.md`, and any global index entry appended by the verb; directory for the ticket key must not exist after rollback.
- CAS push rejected during `ack` — phase must not advance on the remote; holder must not be released locally either (the state was not committed).
- CAS push rejected during `next` — holder must not be set; phase must remain at `P:ack`.
- `pull_rebase` fails (e.g. remote unreachable when feature is on) — verb must exit non-zero before any local mutation; no partial state.
- Identity resolver returns empty string or raises — verb must exit non-zero with a diagnostic; no holder written with blank identity.
- `next` sees `P+1` already held (AC-6b) — must not steal, must surface the holder's identity in the error message.
- Concurrent local `ack` / `next` on same ticket — only one call enters the critical section at a time (AC-9); the second sees a coherent state after the first commits or rolls back.

## Regression scenarios

- All existing `tests/integration/test_gate_policy.py` scenarios (KLC-045) continue to pass: `ack --auto` gate-policy validation is unaffected by the new release-holder + CAS-push wrapping.
- `tests/test_intake_routing.py` — intake routing logic is unchanged in feature-off mode (AC-8).
- `tests/integration/test_build_evidence_gate.py` — build evidence gate still fires; the ack verb's new wrapping does not skip or reorder it.
- `tests/integration/test_retrack.py` — retrack path (ack with non-forward transition) does not acquire or release a holder.
- Any test that calls `intake.run()`, `ack.run()`, or `next.run()` with the feature off (`.klc` is a plain dir, not a `klc-state` worktree) must produce byte-for-byte identical results to the pre-KLC-057 behaviour (AC-8 catch-all).

## Detailed coverage
<!-- TBD — populated in phase 4 after Design -->

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
