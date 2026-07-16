---
ticket: KLC-061
adr: KLC-061-wrap-forward-holder-verbs-in-state-tx
status: accepted
date: 2026-07-16
authority: human
deciders: developer@example.com
risk_tags: [data, migration]
---

# ADR — KLC-061: wrap forward/holder verbs in the state_tx envelope

## Context

KLC-057 delivered `core/skills/state_tx.py`, the self-healing sync envelope
(`self-heal → pull → body → glob-commit + CAS-push`, with a class-closing
stale-guard, deferred-Jira, and full subtree rollback), and wired `intake`,
`ack`, and `next` into it. The remaining state-mutating verbs — `ship`, `steal`,
`abort`, `jump`, and `jira` — shipped before that envelope existed and still
mutate shared tracked state directly under the per-ticket lock only.

The KLC-053..060 review found this reintroduces the exact P1 divergence
`state_tx` was built to prevent:

- `klc ship` (`core/phases/ship.py:85-92`) calls `apply_ack` then
  `advance_to_next` directly and `set_state` fires Jira immediately, but there is
  no CAS push — the phase advance only reaches origin riding a *later* verb's
  push, while Jira is already advanced. (fresh-A MEDIUM)
- `klc steal` (`core/phases/steal.py:87-91`) mutates `meta.holder` under the
  local lock with no pull/CAS-push cycle — a steal can be based on stale local
  holder data and stays only in the caller's worktree; origin still shows the old
  holder, so other users stay blocked. (codex P1)

ADR triggers met: a new intra-`core/phases` dependency edge is added (a verb
calls another verb's `run()`), and an architecturally-significant behavioural
guarantee is relaxed (ship's single-lock atomicity).

## Decision

Adopt **Option A**: reuse the already-wrapped verbs and mirror the ack/next tx
shape inline for the holder verbs. No change to `state_tx`, `state_sync`,
`holder`, or `phases.yml`.

1. **ship → delegate to `ack.run` + `next.run`.** `ship` performs its pre-flight
   checks (missing-ticket, archived, `:work`/`:ack` guards, pick-required) and
   then calls `ack.run([ticket, --pick N])`; if that returns 0 and the ticket is
   not archived, it calls `next.run([ticket])`. Each delegate manages its own
   `acquire_lock` + `state_tx`, so ship inherits holder-auth, the stale-guard,
   and deferred-Jira from the tested path — no re-implementation of the
   ack+next body.

2. **steal / abort / jump / jira-pull → wrap the mutation body in `state_tx`.**
   Mirror ack/next exactly: run the mutating call inside
   `with state_tx.state_tx(ticket, msg) as tx:`, gate any holder write on
   `if tx is not None:`, and translate `StaleStateError` / `StashConflictError`
   / `HolderConflictError` / `StateConflictError` /
   (`RetryExhausted`|`RebaseConflict`|`Config`|`RuntimeError`) into the same
   clean, git-internals-free exit-1 messages the ack/next verbs use.

```
# holder verbs (steal/abort/jump), feature-ON path:
with acquire_lock(ticket):
    with state_tx.state_tx(ticket, msg) as tx:   # pull on enter; no-op if OFF
        <mutate meta / phase>                    # body — after the pull
        if tx is not None:
            holder.acquire_holder / release_holder(...)   # gated
    # clean exit → glob-commit + single CAS push; deferred Jira flushed
    # any failure → subtree rollback + index reset; Jira discarded
```

### D-002 — ship's atomicity relaxation (the load-bearing decision)

`acquire_lock` (`core/skills/artefacts.py:72-99`) writes a PID lockfile and
**unlinks it on context exit**; it raises `LockedError` only for a *different*
live PID. A nested `acquire_lock` in the same process therefore does not
deadlock, but the inner delegate's exit deletes the lockfile out from under the
outer context. So ship **cannot** keep its own lock while delegating.

Consequence: ship becomes **two independently-atomic CAS transactions** (ack,
then next) rather than one. This relaxes ship's original docstring guarantee
("ack + next under a single lock so no concurrent command can interleave").
This is safe because the intermediate `<P>:ack` state is a **valid, re-pullable
resting point**: a concurrent reader sees a coherent acked ticket, and `next.run`
re-pulls before advancing. If the second (next) push is rejected, the ticket
rests at `<P>:ack` and ship exits non-zero pointing at `klc next`. ship's
docstring is updated to state this explicitly.

### D-003 — holder lifecycle for abort / jump

Mirrors ack/next: `abort` leaves a held `<X>:work` state, so it RELEASES that
phase's holder inside the tx (like ack releasing on forward transition); `jump`
enters a fresh `<target>:work`, so it ACQUIRES the target holder (like next
first-grabbing). A `HolderConflictError` (operating over a phase held by another
user) is surfaced with the holder id — never a silent cross-user steal.

### D-004 — jira scope

`jira reconcile pull`/`force-pull` and `jira sync --apply` mutate tracked state
under `tickets/<K>/meta.json` (phase, or `jira_sync` bookkeeping) → wrapped in
`state_tx`. `jira reconcile push` and `jira status` write only to the external
Jira service or read → documented per-verb no-op (AC-3).

## Consequences

- **Positive:** ship/steal/abort/jump/jira-pull all become durable-on-origin,
  holder-authorized, and deferred-Jira-correct with minimal, mirror-of-ack/next
  diffs; the change is fail-safe-OFF and fuzz + real-substrate tested.
- **Negative / accepted:** ship is no longer a single atomic push; the
  intermediate `:ack` state is now observable (documented, safe).
- **Follow-up:** if a future need for true single-push ship atomicity arises,
  Option B (one tx over apply_ack+advance) is the escalation path — deferred as
  YAGNI.
