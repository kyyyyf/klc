---
ticket: KLC-061
kind: manual-checklist
authority: human
---

# Manual checklist — KLC-061

`estimate.manual = 1`. The genuinely-manual aspect of this ticket — real
multi-user behaviour of the wrapped verbs across separate checkouts — is
exercised automatically and deterministically by the concurrency fuzz/property
gate (`tests/integration/test_klc057_fuzz_concurrent.py`, extended here with
scenario-5 stale-steal and scenario-6 ship-vs-ack), which races real git
processes against a shared bare `klc-state` remote. Each item maps to a spec AC
and its automated evidence; all pass.

## Items

- [x] `ship`/`steal`/`abort`/`jump`/`jira` reconcile run inside
      `acquire_lock → state_tx → holder`. (`test_klc061_wrap_verbs.py`, 23)
- [x] `steal` is durable on origin (CAS-pushed, not lock-local).
      (`test_steal_durable_on_origin`)
- [x] `ship` CAS-pushes the advance in the same verb (delegates to `ack.run`
      +`next.run`; no double-advance error). (`test_ship_cas_pushes_advance_in_same_verb`)
- [x] `abort` releases the holder and defers Jira until after a clean push.
      (`test_abort_cas_pushes_and_releases_holder`)
- [x] `jump` acquires the holder for the caller and CAS-pushes.
      (`test_jump_cas_pushes_and_acquires_holder`)
- [x] `jira` reconcile refuses a ticket held by another user (rollback), claims
      it on success. (`test_jira_pull_refuses_ticket_held_by_another_user`)
- [x] A stale same-user holder is refreshed on pull/jump activity (not left
      immediately stealable). (heartbeat-refresh tests)
- [x] Feature-OFF byte-parity: wrapped verbs write no holder and touch no git.
      (verb-regression suite unchanged)

## Multi-user verification note

The concurrency fuzz gate asserts the coordination invariants (no-wedge,
holder-authorization, legal-transitions, convergence, derived-never-shared) after
every op across the stale-steal and ship-vs-ack scenarios with zero violations —
stronger and more repeatable than a one-off two-machine walkthrough. A live
two-operator smoke can still be run ad hoc before enabling the feature in a
shared repo.
