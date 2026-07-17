---
ticket: KLC-061
phase: design
authority: human
last_generated: 2026-07-16
picked_option: A
adr: design/adr.md
---

# Implementation plan — KLC-061

Wrap the forward/holder verbs (`ship`, `steal`, `abort`, `jump`, `jira`) in the
existing `state_tx` envelope, mirroring the KLC-057 wiring of `ack`/`next`. No
change to `state_tx`, `state_sync`, `holder`, or `phases.yml` — the verbs only
import and call the existing surface.

Riskiest work first: `steal` (concurrency + real-substrate CAS-rollback) and
`ship` (the atomicity relaxation, D-002) precede the mechanical `abort`/`jump`/
`jira` wraps. Tests are written RED first at the public verb entry point
(`<verb>.run`), confirmed failing, then made GREEN. Integration tests use a local
bare-repo `klc-state` fixture — no network. Feature-OFF assertions guard AC-5
byte parity on every verb.

## step-1 [x] — wrap `klc steal` holder mutation in state_tx

**Goal:** `steal` runs `holder.steal_holder(ticket, identity, ttl_seconds, on_takeover)` inside `state_tx` so the
takeover is pull-then-mutate-then-CAS-push and durable on origin (AC-2); a
rejected push leaves a clean local state (AC-6 real-substrate).

**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_steal_durable_on_origin`
and `::test_steal_failed_cas_push_leaves_clean_state` — fail today because
`steal.run` does no pull/push (holder change never reaches origin; there is no
rollback on a rejected push). Cite test-plan rows AC-2 and AC-6 (real-substrate).

**GREEN:** In `core/phases/steal.py::run`, move the `holder.steal_holder` call
inside `with state_tx.state_tx(args.ticket, f"steal {args.ticket}") as tx:`
within the existing `acquire_lock` block. Because the staleness check lives
inside `steal_holder`, running it in the tx body means it reads `meta.holder`
AFTER the pull (C-005). Add the ack/next-style except-ladder mapping
`StaleStateError` / `StashConflictError` / `StateConflictError` /
(`RetryExhausted`|`RebaseConflict`|`Config`|`RuntimeError`) to clean exit-1.
Keep the existing `HolderActiveError` / `ValueError` / `HolderConflictError`
handling.

**VERIFY:** `cd $PROJECT_ROOT && python -m pytest tests/integration/test_klc061_wrap_verbs.py -k steal -x -q`

**Expected:** `4 passed` (durable-on-origin; staleness-after-pull refusal;
failed-CAS clean state; feature-off no-op).

**COMMIT:** `KLC-061 step-1: wrap klc steal holder mutation in state_tx`

**Affected files:** `core/phases/steal.py`,
`tests/integration/test_klc061_wrap_verbs.py` (new).

**Interfaces:** none changed (`steal.run(argv) -> int`).

**Depends on:** none.

**Code sketch:**
```python
import state_tx, state_sync  # add to imports
try:
    with acquire_lock(args.ticket):
        with state_tx.state_tx(args.ticket, f"steal {args.ticket}") as tx:
            result = holder.steal_holder(
                args.ticket, identity,
                ttl_seconds=ttl_seconds, on_takeover=_warn_before_takeover,
            )
except holder.HolderActiveError as e:
    sys.stderr.write(f"klc steal: {e}\n"); return 1
except state_sync.StaleStateError:
    sys.stderr.write(f"klc steal: remote state advanced — re-run `klc steal {args.ticket}`.\n"); return 1
except state_sync.StashConflictError:
    sys.stderr.write("klc steal: local changes conflict with the remote — resolve manually.\n"); return 1
except state_sync.StateConflictError:
    sys.stderr.write("klc steal: concurrent update — another writer moved this ticket; retry.\n"); return 1
except (state_sync.RetryExhaustedError, state_sync.RebaseConflictError,
        state_sync.ConfigError, RuntimeError):
    sys.stderr.write("klc steal: state sync failed — retry.\n"); return 1
except (ValueError, holder.HolderConflictError) as e:
    sys.stderr.write(f"klc steal: {e}\n"); return 1
except LockedError as e:
    sys.stderr.write(f"klc steal: {e}\n"); return 1
```

## step-2 [x] — route `klc ship` through ack.run + next.run

**Goal:** `ship` delegates to the already-wrapped `ack.run` then `next.run`
instead of calling `apply_ack`/`advance_to_next` directly, so the phase advance
CAS-pushes to origin within the same `klc ship` invocation and Jira defers to
after each push (AC-1, AC-4). Implements the D-002 atomicity relaxation.

**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_ship_cas_pushes_advance_in_same_verb`
and `::test_ship_routes_through_ack_and_next` — fail today because ship's advance
never reaches origin and no holder release/acquire happens. Cite AC-1 rows.

**GREEN:** Rewrite `core/phases/ship.py::run` to: keep the missing-ticket check;
do NOT hold `acquire_lock` (D-002 / C-004); read `current_state` for the
pre-flight guards (`archived` / `:work` / `:ack` errors and pick-required
message, preserving today's messages); then `rc = ack.run([ticket] + (["--pick",
str(pick)] if pick is not None else []))`; if `rc != 0` return `rc`; re-read
state — if archived, print `ARCHIVED` and return 0; else `return
next.run([ticket])`. Update the module docstring to state ship is now two
independently-atomic CAS steps with a valid `:ack` resting point.

**VERIFY:** `cd $PROJECT_ROOT && python -m pytest tests/integration/test_klc061_wrap_verbs.py -k ship -x -q`

**Expected:** `3 passed` (advance-on-origin-same-verb; delegation holder
lifecycle; feature-off byte-identical).

**COMMIT:** `KLC-061 step-2: route klc ship through wrapped ack.run + next.run`

**Affected files:** `core/phases/ship.py`,
`tests/integration/test_klc061_wrap_verbs.py`.

**Interfaces:** none changed (`ship.run(argv) -> int`); new internal calls
`ack.run` / `next.run`.

**Depends on:** step-1 (shares the test-file fixtures).

**Code sketch:**
```python
import ack as _ack
import next as _next
# ... pre-flight guards on current_state (archived / :work / :ack / pick-required) ...
pick_args = ["--pick", str(args.pick)] if args.pick is not None else []
rc = _ack.run([args.ticket, *pick_args])
if rc != 0:
    return rc
cur = _lc.current_state(args.ticket)
if cur == _ph.STATE_ARCHIVED:
    print(f"ARCHIVED {args.ticket}")
    return 0
return _next.run([args.ticket])
```

## step-3 [x] — wrap `klc abort` in state_tx + release holder

**Goal:** `abort` runs `lifecycle.abort` inside `state_tx` and releases the
aborted phase's holder, so the supersede + budget reset + phase move + holder
release reach origin in one CAS push with deferred Jira (AC-3, AC-4). (D-003)

**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_abort_cas_pushes_and_releases_holder`
— fails today (abort mutates locally only, never releases holder, Jira fires
eagerly). Cite AC-3 row.

**GREEN:** In `core/phases/abort.py::run`, wrap `_lc.abort(args.ticket)` in
`with state_tx.state_tx(args.ticket, f"abort {args.ticket}") as tx:`; after the
abort, `if tx is not None:` call `holder.release_holder(args.ticket, ident)` with
`ident = {"id": identity.current(), "machine": socket.gethostname()}`. Add the
ack/next except-ladder. Keep the existing `ValueError`/`LockedError` handling.

**VERIFY:** `cd $PROJECT_ROOT && python -m pytest tests/integration/test_klc061_wrap_verbs.py -k abort -x -q`

**Expected:** `2 passed` (CAS-push + holder release on origin; feature-off no-op).

**COMMIT:** `KLC-061 step-3: wrap klc abort in state_tx and release holder`

**Affected files:** `core/phases/abort.py`,
`tests/integration/test_klc061_wrap_verbs.py`.

**Interfaces:** none changed (`abort.run(argv) -> int`).

**Depends on:** step-1.

**Code sketch:**
```python
import socket, identity, holder, state_tx, state_sync  # add imports
with acquire_lock(args.ticket):
    with state_tx.state_tx(args.ticket, f"abort {args.ticket}") as tx:
        new_state = _lc.abort(args.ticket)
        if tx is not None:
            ident = {"id": identity.current(), "machine": socket.gethostname()}
            holder.release_holder(args.ticket, ident)
    print(f"ABORTED → {new_state}")
    ...
# + StaleStateError / StashConflictError / HolderConflictError /
#   StateConflictError / (RetryExhausted|RebaseConflict|Config|RuntimeError)
#   → clean exit-1, mirroring ack/next
```

## step-4 [x] — wrap `klc jump` (apply path) in state_tx + acquire holder

**Goal:** `jump --yes` runs `lifecycle.jump(ticket, target_phase, dry_run=False)` inside
`state_tx` and acquires the target phase's holder, so the supersede + budget
reset + phase move + holder acquire reach origin in one CAS push (AC-3). Dry-run
stays a pure no-op (writes nothing, no tx). (D-003, D-004)

**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_jump_cas_pushes_and_acquires_holder`
and `::test_jump_dryrun_and_jira_push_are_documented_noops` — fail today. Cite
AC-3 rows.

**GREEN:** In `core/phases/jump.py::run`, leave the dry-run branch untouched
(returns before any mutation). Wrap the `--yes` apply: call
`_lc.jump(args.ticket, args.target_phase, dry_run=False)` inside `state_tx`;
`if tx is not None:` call `holder.acquire_holder(args.ticket, ident)`. Add the
ack/next except-ladder.

**VERIFY:** `cd $PROJECT_ROOT && python -m pytest tests/integration/test_klc061_wrap_verbs.py -k jump -x -q`

**Expected:** `3 passed` (apply CAS-push + holder acquire; dry-run no-op;
feature-off no-op).

**COMMIT:** `KLC-061 step-4: wrap klc jump apply in state_tx and acquire holder`

**Affected files:** `core/phases/jump.py`,
`tests/integration/test_klc061_wrap_verbs.py`.

**Interfaces:** none changed (`jump.run(argv) -> int`).

**Depends on:** step-1.

**Code sketch:**
```python
import socket, identity, holder, state_tx, state_sync  # add imports
with acquire_lock(args.ticket):
    if not args.yes:
        plan = _lc.jump(args.ticket, args.target_phase, dry_run=True)
        ...  # print plan, return 0  (NO tx — documented no-op, AC-3)
    with state_tx.state_tx(args.ticket, f"jump {args.ticket}") as tx:
        plan = _lc.jump(args.ticket, args.target_phase, dry_run=False)
        if tx is not None:
            ident = {"id": identity.current(), "machine": socket.gethostname()}
            holder.acquire_holder(args.ticket, ident)
    ...  # render prompt card as today
```

## step-5 [x] — wrap `klc jira` state-mutating subcommands in state_tx

**Goal:** `jira reconcile pull`/`force-pull` (calls `set_state` via
`jira_sync.pull` → `lifecycle.jira_pull`) and `jira sync --apply` (writes
`meta.jira_sync`) run inside `state_tx` so their tracked-state mutation
CAS-pushes; `jira reconcile push` and `jira status` stay documented no-ops
(external/read-only). (AC-3, AC-4, D-004)

**RED:** `tests/integration/test_klc061_wrap_verbs.py::test_jira_pull_wrapped_in_state_tx`
and `::test_jira_deferred_until_clean_cas_push` / `::test_jira_discarded_on_rollback`
(stubbed Jira client) — fail today (jira pull mutates phase with no CAS push).
Cite AC-3/AC-4 rows.

**GREEN:** In `core/phases/jira.py`, wrap the mutation in `_reconcile_pull`
(around the `_js.pull` call) and in `cmd_sync`'s `--apply` branch (around
the `upsert_artifact_links` + `_js._update_jira_sync_meta` writes) in
`with state_tx.state_tx(key, f"jira {key}") as tx:`. Add the ack/next
except-ladder. Leave `_reconcile_push` and `cmd_status` unchanged with an inline
comment justifying the no-op (they touch no klc tracked state).

**VERIFY:** `cd $PROJECT_ROOT && python -m pytest tests/integration/test_klc061_wrap_verbs.py -k jira -x -q`

**Expected:** `3 passed` (pull CAS-push + deferred Jira; discard-on-rollback;
push/status no-op).

**COMMIT:** `KLC-061 step-5: wrap jira reconcile-pull and sync --apply in state_tx`

**Affected files:** `core/phases/jira.py`,
`tests/integration/test_klc061_wrap_verbs.py`.

**Interfaces:** none changed.

**Depends on:** step-1.

**Code sketch:**
```python
import state_tx, state_sync  # add imports
# _reconcile_pull:
with state_tx.state_tx(key, f"jira-pull {key}") as tx:
    result = _js.pull(key, to_phase, force=force, reason=reason or None)
# _reconcile_push / cmd_status: unchanged — no klc tracked-state mutation
#   (writes only to the external Jira service, or reads) → documented no-op.
```

## step-6 [x] — extend the concurrency fuzz harness with ship + steal

**Goal:** Extend `tests/integration/test_klc057_fuzz_concurrent.py` so the
op-dispatch table and scenarios include `ship` and `steal` operations and
re-assert the same seven invariants (no-wedge, no-deadlock, no-data-loss,
holder-auth, legal-transitions, convergence, derived-never-shared). (AC-6)

**RED:** the new scenario functions (e.g.
`test_scenario5_concurrent_steal_of_stale_holder` and adding `steal`/`ship` to
the scenario-4 mixed-load op menu) fail before steps 1-2 land because
steal/ship do not participate in the CAS-race barrier (no push) and diverge.

**GREEN:** Add `ship`/`steal`/`abort`/`jump` modules to the worker `mods` dict
(`_worker`). Add a `steal` scenario: two workers race to steal a stale-held
ticket against the shared bare origin under the barrier — assert exactly one
wins, the loser clean-aborts, and the holder converges to a single stealer on
origin (holder-auth + convergence). Add `steal` to the scenario-4 mixed-load
menu. For `ship` (compound: two CAS pushes → two barrier arrivals), exercise it
in the mixed-load scenario (no strict 2-party barrier) per Q-004; do NOT put ship
in a fixed-party barrier race. Re-run the existing 7-invariant assertion helper
after each round.

**VERIFY:** `cd $PROJECT_ROOT && KLC_FUZZ_CONC_ROUNDS=20 python -m pytest tests/integration/test_klc057_fuzz_concurrent.py -x -q`

**Expected:** all scenarios pass (existing intake/ack/next + new steal/ship);
`steal_findings == 0`, no wedge/deadlock, holder converges.

**COMMIT:** `KLC-061 step-6: extend concurrency fuzz harness with ship + steal`

**Affected files:** `tests/integration/test_klc057_fuzz_concurrent.py`.

**Interfaces:** none (test-only).

**Depends on:** step-1, step-2.

**Code sketch:**
```python
import steal as steal_mod
import ship as ship_mod
import abort as abort_mod
import jump as jump_mod
mods = {"intake": intake_mod, "ack": ack_mod, "next": next_mod,
        "steal": steal_mod, "ship": ship_mod,
        "abort": abort_mod, "jump": jump_mod}

# scenario 5 — concurrent steal of a stale holder (single-push → barrier-safe)
def test_scenario5_concurrent_steal_stale_holder(tmp_path):
    # seed a STALE holder on origin; two users race `klc steal` under the barrier
    results = _spawn_race([(users[0], "steal", [key]),
                           (users[1], "steal", [key])])
    # assert: exactly one STOLEN, loser clean-aborts, holder converges on origin
```
