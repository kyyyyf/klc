---
ticket: KLC-061
kind: tech
authority: human
last_generated: 2026-07-16T09:20:00Z
risk_tags: [data, migration]
---

# KLC-061 — Wrap forward/holder verbs (ship, steal, abort, jump, jira) in state_tx

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

## Problem / Context

KLC-057 wired the three core verbs (`intake`/`ack`/`next`) into the self-healing
`state_tx` sync envelope. The forward/holder verbs shipped before that envelope
existed and were never migrated. They mutate shared tracked state directly and
push Jira eagerly, reintroducing the exact P1 divergence `state_tx` was built to
prevent.

FACT: `state_tx(ticket, msg)` is a context manager that, feature-ON, does
`ensure_derived_ignored → pull_rebase_preserving → stale-guard (ticket subtree
hash) → snapshot → defer_jira_pushes → <body> → commit_and_push_cas_subtree →
flush_jira_pushes`, and on ANY body/push failure restores the subtree snapshot,
resets the index, and DISCARDS the deferred Jira push. Feature-OFF it yields
`None` and touches no git — callers gate holder writes on `if tx is not None:`.
src=core/skills/state_tx.py:83-138 verified=2026-07-16

FACT: `ack.run` runs `apply_ack` + `release_holder` inside `state_tx`; `next.run`
runs `advance_to_next` + `acquire_holder`/`release_holder` inside `state_tx`.
Both gate the holder write on `if tx is not None:` and translate
`StaleStateError`/`StashConflictError`/`HolderConflictError`/`StateConflictError`
/sync errors into clean exit-1 messages. src=core/phases/ack.py:259-316,
core/phases/next.py:91-157 verified=2026-07-16

FACT: `klc ship` calls `_lc.apply_ack` then `_lc.advance_to_next` directly under
`acquire_lock` only — NO `state_tx`, NO pull, NO CAS push, NO holder management.
src=core/phases/ship.py:48-108 verified=2026-07-16

FACT: `klc steal` calls `holder.steal_holder(...)` under `acquire_lock` only — it
mutates `meta.holder` and returns, with NO `state_tx`, NO pull, NO CAS push.
src=core/phases/steal.py:85-108 verified=2026-07-16

FACT: `lifecycle.set_state` pushes Jira **immediately** unless a deferral is
active (`_jira_deferral is not None`), which is set only by
`lifecycle.defer_jira_pushes()` — the context manager `state_tx` enters. So any
verb that calls `set_state` outside `state_tx` fires Jira before (and independent
of) any CAS push. src=core/skills/lifecycle.py:420-445, state_tx.py:118
verified=2026-07-16

FACT: `klc abort` (`lifecycle.abort`) and `klc jump` (`lifecycle.jump`) both call
`supersede_phases` + `_reset_budgets` + `set_state` — all shared-tracked-state
mutations — under `acquire_lock` only, no `state_tx`. src=core/phases/abort.py:44-49,
core/phases/jump.py:79-99, core/skills/lifecycle.py:642-733 verified=2026-07-16

FACT: `klc jira reconcile pull`/`force-pull` calls `jira_sync.pull` →
`lifecycle.jira_pull` → `set_state`, which mutates `meta.phase`; `reconcile push`
(`jira_sync.push`) writes only to the external Jira service and does not mutate
klc tracked state. src=core/phases/jira.py:191-289, core/skills/lifecycle.py:465-471
verified=2026-07-16

FACT: `acquire_lock` writes a PID lockfile and **unlinks it on context exit**; it
only raises `LockedError` when a *different* live PID holds it. A nested
`acquire_lock` in the same process therefore does not deadlock, but the inner
context's exit deletes the lockfile out from under the outer context. So a verb
that holds the lock cannot safely delegate to another verb's `run()` (which
re-acquires and then unlinks). src=core/skills/artefacts.py:72-99 verified=2026-07-16

FACT: the KLC-057 concurrency fuzz harness spawns real OS processes against a
shared bare origin, arms a `multiprocessing.Barrier` by monkeypatching
`state_sync.commit_and_push_cas_subtree` to `barrier.wait()` before the real
push, and dispatches verbs via a `mods = {"intake", "ack", "next"}` table. It
asserts who-wins-agnostic invariants across 4 scenarios.
src=tests/integration/test_klc057_fuzz_concurrent.py:168-179,283-422 verified=2026-07-16

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

## Non-goals

- Changing the `state_tx` envelope, the git-CAS primitive (`state_sync`), the
  holder pure-logic model (`holder`), or `phases.yml` state-machine semantics —
  this ticket only wraps existing verbs in the existing envelope.
- Adding new coordination primitives, a registry, or a forge API.
- Changing the staleness policy of `steal` (TTL semantics), the plan/warning
  output shape of `jump`, or the artefact-supersede rules of `abort`/`jump`.
- Building holder heartbeat, `klc remind`, or board holder display (already
  delivered by KLC-058..060).
- Migrating `klc jira sync --apply` (a meta.jira_sync bookkeeping write) — see
  Q-002; if design finds it mutates tracked state it is folded in, otherwise it
  stays out of scope with the read-only/push justification.

## Constraints

> [!CONSTRAINT C-001] source=core/skills/state_tx.py:83-138
> There is exactly ONE sync seam: `state_tx`. Every wrapped verb must route its
> mutation through it and must not re-implement pull/push/rollback. The stale-guard,
> deferred-Jira, and rollback are the envelope's job, not the verb's.

> [!CONSTRAINT C-002] source=core/phases/ack.py:259-316, next.py:91-157
> Mirror the established ack/next shape: run the mutation in the tx body, gate
> holder writes on `if tx is not None:`, and translate
> StaleStateError / StashConflictError / HolderConflictError / StateConflictError
> / (RetryExhausted|RebaseConflict|Config|RuntimeError) into the same clean,
> git-internals-free exit-1 messages. No new failure vocabulary on success paths.

> [!CONSTRAINT C-003] source=AC-5, state_tx.py:85-88
> Feature-OFF must stay a byte-for-byte no-op: `state_tx` yields `None`, so all
> holder mutations are gated on the yielded handle and the feature-off path runs
> the verb body exactly as today.

> [!CONSTRAINT C-004] source=core/skills/artefacts.py:72-99
> `acquire_lock` unlinks its lockfile on context exit and is not safely
> re-entrant across a delegated `run()`. If `ship` delegates to `ack.run` +
> `next.run`, it must NOT hold `acquire_lock` itself while delegating; the two
> steps become two independently-atomic CAS transactions (an intermediate
> `<P>:ack` state is a valid, re-pullable resting point). Document this
> atomicity relaxation explicitly.

> [!CONSTRAINT C-005] source=state_tx.py:96-112
> The stale-guard rejects a verb whose pre-tx validation ran against state the
> pull then changed. `steal` therefore must compute staleness INSIDE the tx body
> (after the pull), and any verb's pre-flight validation that reads shared state
> must tolerate a `StaleStateError` re-run.

## Affected modules

- core/phases: home of the five verb modules being wrapped — `ship.py`,
  `steal.py`, `abort.py`, `jump.py`, `jira.py`. src=core/phases/{ship,steal,abort,jump,jira}.py
- ack: `ship` delegates to `ack.run` (and `next.run`) rather than calling
  `apply_ack`/`advance_to_next` directly; the `ack` verb module is part of the
  delegation contract (its run() signature/return semantics are relied on).
  src=core/phases/ack.py:56-347
- core/skills: consumer-side glue — `state_tx`, `holder`, `identity`,
  `state_feature`, `state_sync`, and possibly `lifecycle` (abort/jump/jira_pull
  bodies run inside the tx; holder acquire/release for abort/jump). No new API is
  added here; the verbs import and call the existing surface.
  src=core/skills/{state_tx,holder,lifecycle,state_sync}.py
- tests: extend `tests/integration/test_klc057_fuzz_concurrent.py` (fuzz +
  op-dispatch) and add real-substrate rollback tests plus feature-off parity
  tests for the wrapped verbs. src=tests/integration/test_klc057_fuzz_concurrent.py

(All names are members of modules.json. `ship`/`steal`/`abort`/`jump`/`jira` are
not distinct module names; they are folded into `core/phases`, exactly as
KLC-057 folded `next`.)

## Approaches (shortlist — detail in design/options.md)

- Option A — **Delegate ship to ack.run+next.run; wrap steal/abort/jump/jira-pull
  bodies in state_tx directly** (the reviewer's prescription). ship reuses the
  already-wrapped verbs; the holder verbs mirror the ack/next tx shape inline.
- Option B — **Inline a fresh state_tx in ship** that calls `apply_ack` +
  `advance_to_next` in one tx body (one CAS push for both), instead of delegating.
- Option C — **Push the envelope down into `lifecycle.apply_ack` /
  `advance_to_next` / `abort` / `jump`** so every caller inherits it and the
  verbs stay untouched.

Picked: **Option A** — it is the smallest, lowest-risk change that reuses the
exact ack/next code paths KLC-057 already hardened and fuzz-tested, so ship
inherits holder-auth + stale-guard + deferred-Jira for free rather than
re-deriving them. Option B keeps ship's single-lock atomicity but re-implements
the ack+next body (duplicating the fragile ordering the reviewer specifically
wants routed through the tested path). Option C was rejected for the same reason
KLC-057 rejected its Option C: hiding network I/O inside the pure lifecycle layer
makes it non-deterministic and hard to keep a byte-identical feature-off no-op.
The only cost of A is the atomicity relaxation in C-004, which is safe because
the intermediate `:ack` state is a valid resting point.

## Open questions

> [!QUESTION Q-001] blocks=design — RESOLVED (C-004)
> Can `ship` keep its single `acquire_lock` while delegating to `ack.run` +
> `next.run`? Resolved: NO — `acquire_lock` unlinks on inner exit and is not
> re-entrant across a delegated run(). `ship` drops its own lock and delegates
> sequentially; each delegate manages its own lock + state_tx. The two steps are
> two independently-atomic CAS transactions; the intermediate `<P>:ack` is a
> valid resting point. Design pins the exact ship control flow (pre-flight
> checks, --pick pass-through, archived short-circuit, exit-code propagation).

> [!QUESTION Q-002] blocks=design
> Does `klc jira sync --apply` (which calls `jira_sync._update_jira_sync_meta`,
> writing `meta.jira_sync`) count as a shared-tracked-state mutation that must be
> wrapped, or is `meta.jira_sync` a local bookkeeping field excluded from the
> CAS-pushed state? Design must decide and either wrap it or document the
> exclusion with justification (AC-3 allows a justified per-verb no-op).

> [!QUESTION Q-003] blocks=design
> Holder handling for `abort` and `jump`: `abort` leaves a `<X>:work` state (the
> holder is currently held) → it should RELEASE the aborted phase's holder inside
> the tx (mirroring ack). `jump` leaves an `:ack` state (holder already released)
> and enters `<target>:work` → it should ACQUIRE the target holder (mirroring
> next). Design confirms this is the intended lifecycle and whether a
> HolderConflictError on abort/jump is possible (e.g. aborting a phase held by
> another user) and how it is surfaced.

> [!QUESTION Q-004] blocks=test-planner
> Ship is a compound op (two CAS pushes) under the barrier-race fuzz harness,
> which arms exactly one `barrier.wait()` per `commit_and_push_cas_subtree`. Test
> design must decide how ship participates: exercise ship in the mixed-load
> scenario (scenario 4, no strict barrier) rather than the strict 2-party barrier
> races, or teach the barrier to tolerate a variable push count. steal is a
> single-push op and slots into the barrier scenarios directly.

## Estimate

- complexity: 2  (five verbs, delegation + tx-body wrapping, holder lifecycle for
  abort/jump, ship's atomicity relaxation; not cross-architecture — it applies an
  existing envelope)
- uncertainty: 1  (the envelope, the ack/next shape, and the fuzz harness all
  already exist and are tested; the fix is mechanical mirroring — open questions
  are scoping, not spikes)
- risk: 2  (klc-state branch writes across collaborators; a wrong ordering or a
  missed rollback leaves inconsistent shared state — risk_tags: data, migration;
  but fail-safe-off by default and covered by fuzz + real-substrate tests)
- manual: 1  (autotestable via the extended fuzz harness + local bare-repo
  fixtures; light manual sanity of the real multi-collaborator ship/steal flow)
- total: 6
- track: M

blast-radius: available (partial) — `core/phases` has `depended_by: [tests]` and
no external dependents; the verbs are internal-tooling entrypoints of the
lifecycle with no consumers outside this repo. src=.klc/index/modules.json
verified=2026-07-16. The route_hint floor (S) is held and not downgraded; the
score independently lands at M (total=6) and the full `discovery` phase runs only
on M/L, so classifying M is both an operator-forced (pick 2) and score-consistent
upgrade — appropriate for concurrency/shared-state work per the risk-based floor.
