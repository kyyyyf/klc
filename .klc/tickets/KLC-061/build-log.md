# Build log — KLC-061

Wrap the remaining state-mutating verbs (`ship`/`steal`/`abort`/`jump`/`jira`
reconcile) in KLC-061's `acquire_lock → state_tx → holder` envelope, so they run
like `intake`/`ack`/`next` (CAS-push + holder-auth + deferred-Jira). Built TDD in
an isolated worktree, branch `feature/klc-061-wrap-forward-holder-verbs`,
squash-merged to main as `f833d5a` (PR #65). Design option A-minimal
(`design/adr.md`, D-002: `ship` delegates to `ack.run` (+`next.run` if still
`:ack`) because the old `ship` was already broken — `apply_ack` auto-advances, so
the second advance errored).

Note on TDD evidence: the feature branch was squash-merged, so the per-step
RED→GREEN commits are collapsed into `f833d5a` on main. The RED test names and
the RED→GREEN order are recorded per step below and in `## Evidence`; completed
steps are marked `[x]` in `impl-plan.md`.

## step-1 [x] — wrap `klc steal` holder mutation in state_tx
**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_steal_durable_on_origin` — fails (steal mutates `meta.holder` under the local lock only; never CAS-pushed → not durable on origin).
**GREEN:** wrap the steal holder mutation in `state_tx` so the holder change is pulled → applied → CAS-pushed in one envelope.
**Outcome:** green

## step-2 [x] — route `klc ship` through ack.run + next.run
**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_ship_cas_pushes_advance_in_same_verb` — fails (old `ship` calls `apply_ack` then `advance_to_next` directly with no CAS push; the second advance errors because `apply_ack` already auto-advanced).
**GREEN:** `ship` delegates to `ack.run` (+`next.run` when still `:ack`), inheriting the KLC-057 envelope. Recorded as D-002.
**Outcome:** green

## step-3 [x] — wrap `klc abort` in state_tx + release holder
**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_abort_cas_pushes_and_releases_holder` — fails (abort sets terminal state under the lock only; holder not released, no CAS push, deferred-Jira not flushed after push).
**GREEN:** abort runs inside `state_tx`, releases the holder in the same body, one CAS push carries the state change + cleared holder; Jira deferred to after a clean push.
**Outcome:** green

## step-4 [x] — wrap `klc jump` (apply path) in state_tx + acquire holder
**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_jump_cas_pushes_and_acquires_holder` — fails (jump apply mutates phase under the lock only; no holder acquire, no CAS push).
**GREEN:** jump apply runs inside `state_tx`, acquires the holder for the caller, CAS-pushes the phase move + holder in one envelope.
**Outcome:** green

## step-5 [x] — wrap `klc jira` state-mutating subcommands in state_tx
**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_jira_pull_wrapped_in_state_tx` — fails (jira reconcile pull/force-pull mutate tracked meta outside the envelope; no lock, no holder-auth, no CAS push).
**GREEN:** jira reconcile pull/force-pull run inside `state_tx`. (Advisory `jira sync --apply` / `meta.jira_sync` intentionally NOT wrapped — ratified descope → KLC-065, drift-tracking, not lifecycle state.)
**Outcome:** green

## step-6 [x] — extend the concurrency fuzz harness with ship + steal
**RED:** new scenario functions (scenario-5 stale-steal, scenario-6 ship-vs-ack) — fail until steps 1-5 land and compose with KLC-057's `state_tx`.
**GREEN:** fuzz scenarios 5 and 6 added; 0 invariant violations across the soak.
**Outcome:** green

## Evidence

```
$ python3 -m pytest tests/integration/test_klc061_wrap_verbs.py -q
23 passed
```

```
$ python3 -m pytest tests/integration/test_klc057_fuzz_concurrent.py -q
# scenario-5 (stale-steal) + scenario-6 (ship-vs-ack) added; 0 invariant violations
passed
```

```
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
762 passed
```

Feature-OFF (single-user) byte-parity intact: with the state feature off,
`state_tx` is a no-op wrapper and none of the wrapped verbs touch git or write a
holder — existing verb-regression tests unchanged.

## Review-fix round — 2026-07-16 (fresh general-purpose + `codex exec review --base main`)

Two independent reviewers found non-overlapping real gaps; every finding fixed
TDD (RED→GREEN); the delicate holder-liveness fix got a scoped codex re-review of
the fix delta (clean). Full detail and fix/won't-fix assessment in
`review-report.md`.

- P2 codex + MEDIUM fresh (converged): `jira reconcile` pull/force-pull got the
  envelope but not the per-ticket **lock** nor **holder-auth** → refuses a ticket
  held by another user (rollback) and claims it for the caller on success.
  **RED:** `test_jira_pull_refuses_ticket_held_by_another_user`.
- P2 codex (fix re-review): a stale **same-user** holder was not refreshed on
  pull/jump → immediately stealable → refresh liveness via `heartbeat_holder`
  (first production caller) in `pull` + `jump`.
- LOW: stale `jira.py` module docstring updated; added abort/jump deferred-Jira
  timing tests.

```
$ python3 -m pytest "tests/integration/test_klc061_wrap_verbs.py::test_jira_pull_refuses_ticket_held_by_another_user" -q
1 passed
```

```
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
762 passed
```
