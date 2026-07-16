---
ticket: KLC-057
kind: manual-checklist
authority: human
---

# Manual checklist — KLC-057

`estimate.manual = 1`. The genuinely-manual aspect of this ticket — real
multi-user behaviour across separate checkouts — is exercised automatically and
deterministically by the concurrency fuzz/property gate
(`tests/integration/test_klc057_fuzz.py` sequential + `..._fuzz_concurrent.py`
true-multiprocess), which stands in for a two-machine smoke by racing real git
processes against a shared bare `klc-state` remote. Each item below maps to a
spec AC (verbatim) and its automated evidence; all pass.

## Items

- [x] **AC-1** intake uniqueness happy path — free key → `pull_rebase`, create,
      CAS push, `INTAKE_OK`, exit 0. (fuzz scenario2 winner; sync-holder tests)
- [x] **AC-2** intake taken-key → rejected, "already taken", no partial local
      artifacts. (fuzz scenario2 loser `taken=40`, `_KeyTakenError` tests)
- [x] **AC-3** intake acquires holder in the same CAS push. (sync-holder tests)
- [x] **AC-4** ack releases holder on forward transition. (real-repo, sync-holder)
- [x] **AC-5** ack ordering & atomicity — advance+release ride one push; rejected
      push does not advance remote. (fuzz scenario1 exactly-one-winner `40/40`)
- [x] **AC-6** next first-grab free phase / refuse to steal held. (sync-holder +
      holder-conflict tests; `intake --force` peer-held refused, fuzz scenario3
      `steal_findings=0`)
- [x] **AC-7** hidden from the user on the success path; new text only on
      failure. (output-hygiene tests; terminal sync errors → clean messages)
- [x] **AC-8** feature-off byte-for-byte identical, existing tests pass. (feature
      -off parity tests; zero git touched feature-off)
- [x] **AC-9** sync/holder runs inside the per-ticket `acquire_lock`. (lock-scope
      tests for all three verbs)
- [x] **AC-10** integration tests (local bare repo / stubbed sync, no network).
      (all integration + fuzz use local bare repos)

## Multi-user verification note

The concurrency fuzz gate asserts, after every op and across a 40-round
true-concurrent soak, the seven "clockwork" invariants: no-wedge, no-deadlock,
no-data-loss, holder-authorization, legal-transitions, convergence, and
derived-files-never-shared — with zero violations. This is stronger and more
repeatable than a one-off manual two-machine walkthrough; a live two-operator
smoke can still be run ad hoc before enabling the feature in a shared repo.
