---
ticket: KLC-057
kind: build-log
---

# Build log — KLC-057

Integration spine: wire `state_sync`/`identity`/`holder` into `intake`/`ack`/`next`
via a `state_feature` detector + `state_tx` transaction envelope. Built TDD in an
isolated worktree (8 steps, test-only RED commit then impl GREEN commit each),
branch `feature/klc-057-wire-sync-holder`, rebased onto current main. Design
option B (`design/adr.md`). All wave-1/2 whole-scope-review handoff constraints
baked in (see Notes).

## Steps 1–3 — feature detector + transaction envelope
**Attempt**: `core/skills/state_feature.py::enabled()` (True iff `.klc` HEAD is
the `klc-state` branch AND an upstream resolves — see Note-1); `core/skills/state_tx.py`
`@contextmanager state_tx(ticket, paths, msg)`: no-op when feature off (AC-8);
feature-on = `pull_rebase` on enter, snapshot touched paths, `commit_and_push_cas`
on clean exit, restore snapshot + re-raise on `StateConflictError` (D-002/D-005).
**Outcome**: green
**Notes**: RED per step confirmed (module-missing; NotImplementedError; conflict-
rollback). Adapted to the real KLC-054 API (`pull_rebase(kdir)`,
`commit_and_push_cas(rel_paths, msg, ticket, kdir)`) — the plan's zero-arg sketch
predated it.

## Evidence

```
$ python3 -m pytest tests/test_state_feature.py tests/test_state_tx.py -q
(state_feature + state_tx suites) passed
```

## Steps 4–7 — wire the three verbs
**Attempt**: intake — CAS uniqueness (taken key → `StateConflictError` → rollback,
no artifacts, no index entry, AC-2), holder acquire in the same push (AC-3),
global-index append deferred to after a clean push (D-005); ack — `release_holder`
after advance, before push, one CAS push carries advance+release (AC-4/AC-5);
next — first-grab entered phase, refuse to steal a held phase (`HolderConflictError`
→ "held by", AC-6). All `state_tx` call sites inside the existing
`with acquire_lock(ticket):` block (AC-9).
**Outcome**: green
**Notes**: real KLC-056 API (`acquire_holder`/`release_holder`; `err.holder.get("id")`);
identity `{"id": identity.current(), "machine": socket.gethostname()}` built only
feature-on; `next` skips acquire when advance lands on `archived`.

## Evidence

```
$ python3 -m pytest tests/integration/test_klc057_sync_holder.py -q
(intake/ack/next integration) passed
```

## Step 8 — output hygiene + regression sweep
**Attempt**: no git-internals on success paths (AC-7); feature-off writes no holder
(AC-8); sync inside per-ticket lock (AC-9). Added AC-7 hardening: terminal non-CAS
sync errors (`RetryExhaustedError`/`RebaseConflictError`/`ConfigError`) mapped to a
clean "state sync failed — retry" stderr message in all three verbs (no traceback);
intake also rolls back local artifacts on such failures.
**Outcome**: green

## Evidence

```
$ python3 -m pytest tests/test_state_feature.py tests/test_state_tx.py tests/integration/test_klc057_sync_holder.py -q
18 passed
$ python3 -m pytest tests/ -k "intake or ack or next or gate_policy" -q --ignore=tests/fixtures
107 passed, 602 deselected
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
697 passed, 12 skipped
```

## Notes (handoff constraints applied)

1. **Upstream-gate**: `state_feature.enabled()` requires the `klc-state` worktree
   AND a resolvable `@{upstream}` — a no-remote single-user orphan is feature-OFF
   (state_sync needs upstream), closing the wave-1 whole-scope-review F2 gap.
2. Real KLC-056 names (`acquire_holder`/`release_holder`; `HolderConflictError.holder`).
3. Per-ticket-only CAS payload; global tickets-index append deferred + local
   (no shared hot files → conflict-free per-ticket).
4. Feature-off is byte-for-byte identical (107 verb-regression tests green).
