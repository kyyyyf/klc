---
ticket: KLC-061
phase: design
last_generated: 2026-07-16
---

# Design options — KLC-061

Wrap the forward/holder verbs (`ship`, `steal`, `abort`, `jump`, `jira`) in the
existing `state_tx` envelope so feature-ON multi-user mode gets CAS-push +
holder-auth + deferred-Jira, mirroring the KLC-057 wiring of `intake`/`ack`/`next`.

## Dependency impact

- `depgraph.json` has no per-language edges for these tooling modules
  (`import_graphs` empty), so blast radius is computed from the import structure
  read directly: `core/phases/{ship,steal,abort,jump,jira}.py` import
  `core/skills/{lifecycle,holder,identity,state_tx,state_feature,state_sync,artefacts}`.
  FACT: `state_tx`, `holder`, `identity`, `state_feature`, `state_sync` are the
  exact skills `ack`/`next` already import for the same purpose.
  src=core/phases/ack.py:23-30, core/phases/next.py:26-29 verified=2026-07-16
- **New edge added:** `core/phases/ship.py` will import and call
  `core/phases/ack.py::run` and `core/phases/next.py::run` (Option A/picked). This
  is a NEW intra-`core/phases` edge (a verb calling another verb's `run`). It is
  the crux of the ADR (a verb-to-verb dependency did not exist before). No edge is
  inverted; no cycle is created (ack/next do not import ship).
- **Upstream dependents:** `core/phases` is `depended_by: [tests]` only — no
  consumer outside the repo. The CLI dispatcher `scripts/klc` routes
  `ship`/`steal`/`abort`/`jump`/`jira` to these modules' `run()`; their argv
  contract and exit codes must be preserved (ship's delegation must return the
  same 0/1 semantics). src=.klc/index/modules.json verified=2026-07-16
- **No public-API / schema change:** no function signature in `core/skills`
  changes; `meta.json` shape is unchanged (holder writes reuse the KLC-056/057
  `holder` sub-object). So no persistence migration.

## Option A — Minimal diff (reuse the wrapped verbs) — recommended: true

Route `ship` through the already-wrapped `ack.run` + `next.run` instead of
calling `lifecycle.apply_ack` / `advance_to_next` directly; wrap the mutation
body of `steal` / `abort` / `jump` / `jira reconcile pull` in `state_tx` inline,
mirroring the exact ack/next shape (body in the tx, holder gated on
`if tx is not None:`, the same exception-to-exit-1 translation).

- **Trade-off:** Smallest, lowest-risk diff — ship inherits holder-auth +
  stale-guard + deferred-Jira from the already-fuzz-tested ack/next path — at the
  cost of relaxing ship's "single lock, one atomic step" guarantee into two
  independently-atomic CAS transactions (an intermediate `<P>:ack` resting state).
- **Affected files:** `core/phases/ship.py`, `core/phases/steal.py`,
  `core/phases/abort.py`, `core/phases/jump.py`, `core/phases/jira.py`,
  `tests/integration/test_klc061_wrap_verbs.py` (new),
  `tests/integration/test_klc057_fuzz_concurrent.py` (extended).
- **Affected public APIs:** none (verb `run()` signatures and CLI contract
  unchanged).
- **New dependencies:** none external. New intra-repo edge ship→ack.run/next.run.
- **Risks:** the atomicity relaxation (C-004) — if ship's first CAS push (ack)
  lands but the second (next) is rejected, the ticket rests at `<P>:ack`; the
  test plan covers this as a valid resting state. Mitigated: `<P>:ack` is a
  legal, re-pullable state and ship exits non-zero pointing at `klc next`.
- **Rollout:** immediate; fail-safe-OFF (feature-OFF is a byte-identical no-op).
- **Estimate:** M (roughly 1 day incl. fuzz extension + real-substrate tests).

## Option B — Inline a fresh state_tx in ship (no delegation)

Keep ship's single `acquire_lock` and open ONE `state_tx` whose body calls
`apply_ack` then `advance_to_next` (one CAS push carries both transitions), with
holder release+acquire inline. `steal`/`abort`/`jump`/`jira` wrapped as in A.

- **Trade-off:** Preserves ship's single-push atomicity, but re-implements the
  ack+next body (gate-policy, scope-guard, pick validation, holder ordering) that
  the reviewer specifically wants routed through the already-tested path — a
  second copy of the fragile ordering to keep in sync.
- **Affected files:** same set as A.
- **Affected public APIs:** none.
- **New dependencies:** none.
- **Risks:** duplicated validation drifts from ack/next over time; ship would
  bypass ack's scope-expansion guard and gate-policy unless it re-invokes them —
  easy to miss and exactly the class of gap the reviewer flagged.
- **Rollout:** immediate.
- **Estimate:** M-L (more code, more test surface than A).

## Option C — Push the envelope down into the lifecycle layer

Move `state_tx` wrapping INTO `lifecycle.apply_ack` / `advance_to_next` /
`abort` / `jump` so every caller (verbs and internal recursion) inherits it and
the verb files stay nearly untouched.

- **Trade-off:** One seam for all callers, but it hides network I/O inside the
  pure lifecycle layer, making it non-deterministic and breaking the byte-identical
  feature-OFF no-op that existing tests rely on — the same reason KLC-057 rejected
  its Option C.
- **Affected files:** `core/skills/lifecycle.py` (deep change), all verbs.
- **Affected public APIs:** `lifecycle` internal functions gain implicit I/O.
- **New dependencies:** none.
- **Risks:** re-entrancy — `apply_ack` already calls `advance_to_next` internally,
  so nesting `state_tx` inside both would double-wrap (nested pull/push); the
  KLC-057 envelope is explicitly designed to be entered ONCE per verb. High
  regression risk to the already-shipped intake/ack/next.
- **Rollout:** immediate but invasive.
- **Estimate:** L.

## Decisions

> [!DECISION D-001]
> Pick Option A. It reuses the exact ack/next code paths KLC-057 hardened and
> fuzz-tested, keeps per-verb diffs small, and is the reviewer's prescription.

> [!DECISION D-002] source=core/skills/artefacts.py:72-99 verified=2026-07-16
> ship drops its own `acquire_lock` and delegates to `ack.run` then `next.run`
> sequentially. `acquire_lock` unlinks its lockfile on inner-context exit and is
> not safely re-entrant across a delegated `run()`, so ship holding the lock
> while delegating would corrupt the lock. Consequence: ship becomes two
> independently-atomic CAS transactions; the intermediate `<P>:ack` is a valid
> resting point. This relaxes ship's docstring atomicity claim — documented in
> the ADR and ship's docstring.

> [!DECISION D-003] source=core/phases/next.py:101-107, ack.py:269-272 verified=2026-07-16
> Holder lifecycle for the newly-wrapped verbs mirrors ack/next: `abort` RELEASES
> the aborted `<X>:work` phase's holder (it leaves a held :work state, like ack);
> `jump` ACQUIRES the target `<phase>:work` holder (it enters a new :work state,
> like next). Both gated on `if tx is not None:`. A HolderConflictError (aborting
> or jumping over a phase held by another user) is surfaced with the holder id,
> never a silent steal (steal is the only takeover path).

> [!DECISION D-004]
> `jira reconcile pull`/`force-pull` mutates `meta.phase` via `set_state`, so it
> is wrapped in `state_tx`. `jira reconcile push` and `jira status` write only to
> the external Jira service (or read), touching no klc tracked state → documented
> per-verb no-op (AC-3). `klc jira sync --apply` writes `meta.jira_sync`
> bookkeeping (Q-002): it is folded into the wrap only if `meta.jira_sync` is part
> of the CAS-pushed subtree — it lives under `tickets/<K>/meta.json`, so it IS in
> the pushed subtree; therefore `sync --apply` is also wrapped for durability.
> Resolved: wrap `jira reconcile pull/force-pull` and `jira sync --apply`; leave
> `reconcile push` and `status` as justified no-ops.

ADR_NEEDED=yes
