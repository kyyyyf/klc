# Agent prompt — KLC-061 · build:work · step-1

Ticket: **KLC-061** · track: **M** · kind: **tech**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

- Bring the remaining state-mutating lifecycle verbs under the **same
  `state_tx` envelope** KLC-057 built for `intake`/`ack`/`next`, so that in
  feature-ON multi-user mode every verb that changes shared tracked state does
  the full `self-heal → pull → body → glob-commit + CAS-push` cycle with
  holder-auth, a stale-guard, and deferred-Jira — exactly once, at the same seam.
- Close the two concrete divergence bugs found in the KLC-053..060 review:
  `klc ship` advances the phase and fires Jira **immediately** but never
  CAS-pushes the advance (it only reaches origin riding a *later* verb's push),
  and `klc steal` mutates `meta.holder` under the local lock only — origin still
  shows the old holder, so other users stay blocked.
- Preserve **feature-OFF byte parity**: single-user mode (`.klc/` is a plain
  directory) must behave exactly as today — no pull, no push, no holder writes.
- Extend the KLC-057 concurrency **fuzz harness** and add **real-substrate**
  (local bare-repo) rollback tests so this concurrency-class change is never
  validated only through a stub (the KLC-057 lesson).

## Acceptance Criteria

1. **AC-1 (ship performs the full state_tx cycle):** Given the state-sync feature
   is ON and ticket `K` is at `<P>:ack-needed`, when a user runs
   `klc ship K [--pick N]`, then the ack (`<P>:ack-needed` → `<P>:ack`) and the
   advance (`<P>:ack` → `<P+1>:work`) each run inside a `state_tx` cycle
   (self-heal → pull → body → CAS-push) with holder-auth + stale-guard +
   deferred-Jira exactly like `ack`/`next`, and the phase advance **reaches
   origin within the same `klc ship` invocation** — not riding a later verb's
   push. The prescribed implementation routes `ship` through `ack.run` then
   `next.run` (both already wrapped) rather than calling `apply_ack` /
   `advance_to_next` directly.

2. **AC-2 (steal wraps its holder mutation in state_tx):** Given the feature is ON
   and `K`'s holder is stale, when a user runs `klc steal K`, then the holder
   mutation runs inside `state_tx` (pull → mutate `meta.holder` → CAS-push) so a
   successful steal is **durable on origin**, not only in the caller's local
   worktree; the staleness check is evaluated against the freshly-pulled holder
   (inside the tx body, after the pull), never against stale local state.

3. **AC-3 (abort / jump / jira wrapped or justified per verb):** Given the feature
   is ON, when a user runs `klc abort K`, `klc jump <phase> K --yes`, or a
   `klc jira` subcommand, then every verb that mutates shared tracked state runs
   that mutation inside `state_tx`; specifically: `abort` (supersede + budgets +
   `set_state` back to prev `:ack`, releasing the aborted phase's holder) and
   `jump` (supersede + budgets + `set_state` to target `:work`, acquiring the
   target holder) are wrapped; `jira reconcile pull`/`force-pull` (which calls
   `set_state`) is wrapped. Verbs that mutate **no** shared tracked state are a
   documented no-op with a per-verb justification: `jira reconcile push` and
   `jira status` (read-only / write only to the external Jira service, not to
   klc tracked meta), and `klc jump` **dry-run** (prints a plan, writes nothing).

4. **AC-4 (Jira fires only after a clean CAS push):** Given the feature is ON, for
   every wrapped verb the Jira side-effect fires **only after** the CAS push
   succeeds (via the `state_tx` deferred-Jira flush) and is **discarded** if the
   body or push fails/rolls back — never before the push, and never ahead of the
   klc advance reaching origin.

5. **AC-5 (feature-OFF byte parity):** Given the feature is OFF (`.klc/` is a plain
   directory), when any of `ship`/`steal`/`abort`/`jump`/`jira` runs, then
   behaviour is byte-for-byte identical to today — no pull, no push, no holder
   fields written — and all existing tests for these verbs still pass. Every new
   holder write is gated on `if tx is not None:`.

6. **AC-6 (fuzz extension + real-substrate rollback):** The KLC-057 concurrency
   fuzz harness `tests/integration/test_klc057_fuzz_concurrent.py` is EXTENDED so
   its op-dispatch/scenarios include `ship` and `steal` operations and re-assert
   the same **seven** invariants (no-wedge, no-deadlock, no-data-loss,
   holder-auth, legal-transitions, convergence, derived-never-shared). In
   addition, a **real-substrate** test (a real local bare-repo origin, not a
   stub) asserts that a `klc steal` whose CAS push is rejected leaves a clean
   local state (holder unchanged, tree + index clean, exit non-zero, no
   traceback). Per the KLC-057 lesson, this class is NOT validated through a stub
   alone: the plan REQUIRES both the fuzz extension and real-substrate
   conflict/rollback coverage.

### Current step — step-1

**wrap `klc steal` holder mutation in state_tx**

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

**Affected files**:


**Expected tests**:



### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.

### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/home/ek/projects/klc/.claude/worktrees/agent-a48ff018c25fe5cbc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-061 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-061/impl-plan.md`
- Full spec: `.klc/tickets/KLC-061/spec.md`
- Full test-plan: `.klc/tickets/KLC-061/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-061 step-1` and
run `klc step KLC-061 2` to get the next step's card,
or `klc ack KLC-061 --pick 1` if this was the last step.
