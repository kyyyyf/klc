# KLC-057 — Design options

Wire the multi-user sync + holder primitives (KLC-054 `state_sync`, KLC-055
`identity`, KLC-056 `holder`) into the three lifecycle verbs `intake` / `ack` /
`next`, enforce key uniqueness via git-CAS, and keep everything a no-op when the
state-sync feature is off. The discovery phase already picked **Option B**; the
three options below are re-stated in design form. The differentiator is *where*
the `pull → body → push-with-rollback` envelope lives.

All three consume the **same** import surface (pinned from sibling specs, see
`scout.md` and the ADR):

- `state_sync.pull_rebase()` → None; raises `RebaseConflictError`.
- `state_sync.commit_and_push_cas(paths, msg, max_retries=3)` → None; pushes the
  `klc-state` branch to `origin`; raises `StateConflictError` on same-ticket CAS rejection.
- `identity.current()` → str (email/name/$USER).
- `holder.acquire_holder(ticket, identity_dict)` / `holder.release_holder(ticket, identity_dict)`.

## Dependency impact

`dependency-impact: unavailable (.klc/index/depgraph.json absent; modules.json
has null edges for every module — meta.blast_radius.available=false)`. Fell back
to direct source reading + grep `findReferences`:

- **Downstream (consumed):** `core/skills/{state_sync,identity,holder}` — none in
  the tree yet (KLC-054/055/056). Their **specs** are the authoritative contract;
  this ticket is their consumer spec.
- **Upstream (dependents of the verbs):** only `scripts/klc:_run_phase`
  (src=scripts/klc:90-93,123). The verb `run()` functions are CLI leaves — no
  other core module imports them, so the blast radius of changing the verbs'
  internals is contained to the CLI dispatch + the verbs' own test files.
- **New edges introduced (all options):** `core/phases/*` → the three new skills.
  Options B/C also add a new intra-`core/skills` edge (`state_tx` →
  `state_sync`/`holder`/`identity`). A new dependency edge added → **ADR trigger**.
- **Edge inversion / cycle:** none. The verbs already depend on `core/skills`
  (lifecycle, artefacts, gate_policy); adding three more skill imports follows the
  existing direction. No cycle is created.
- **Dependents outside `affected_modules`:** none — scope holds. `next` lives at
  `core/phases/next.py` and is covered by the `core/phases` module entry (no new
  module ref), per spec.

---

## Option A — Minimal diff: inline the calls in each verb's `run()`

Call `state_sync` / `holder` / `identity` directly at the right points inside
`intake.py`, `ack.py`, `next.py`, mirroring how `ack --auto` inlines gate-policy
(src=core/phases/ack.py:170-191).

- **Trade-off:** smallest conceptual jump and one-file-per-verb visibility, but
  the fragile CAS-rejection rollback path is copy-pasted into three files and will
  drift.
- **Affected files:** `core/phases/intake.py`, `core/phases/ack.py`,
  `core/phases/next.py`, `tests/integration/test_klc057_sync_holder.py`.
- **Affected public APIs:** none renamed; the verbs' `run()` behaviour gains
  feature-on branches (names unchanged).
- **New dependencies:** none external; imports `state_sync`, `identity`, `holder`.
- **Risks:** rollback logic triplicated (the riskiest code, repeated 3×); the
  feature-off no-op short-circuit must be re-added at every call site and is easy
  to miss → AC-8 regression; envelope not unit-testable in isolation.
- **Rollout:** feature-gated by `.klc/` being a `klc-state` worktree; no migration.
- **Estimate:** M (10–14h).

## Option B — Shared `transaction` wrapper (`core/skills/state_tx.py`)  ← recommended: true

One context manager implements the envelope once: `pull_rebase` on enter,
verb body mutates local `.klc` state, on clean exit `commit_and_push_cas`, on
`StateConflictError` roll back the local mutations. It short-circuits to a pure
no-op when `.klc/` is not a worktree bound to the `klc-state` branch. Each verb
supplies only its body and is called **inside** the existing `acquire_lock(ticket)` block.

```python
with state_tx(ticket, paths_to_push, msg) as tx:   # pull on enter; no-op if feature off
    ... verb-specific body: mutate .klc + holder ...
# clean exit → commit_and_push_cas; StateConflictError → tx rolled back local state
```

- **Trade-off:** one new abstraction to introduce and document, in exchange for
  the fragile rollback existing exactly once and a single, testable no-op seam.
- **Affected files:** `core/skills/state_tx.py` (new), `core/skills/state_feature.py`
  (new, feature detector), `core/phases/intake.py`, `core/phases/ack.py`,
  `core/phases/next.py`, `tests/integration/test_klc057_sync_holder.py`,
  `tests/test_state_tx.py`.
- **Affected public APIs:** new `state_tx` (context manager) and `state_feature`
  (detector) in `core/skills`; verbs' `run()` unchanged in name/output shape.
- **New dependencies:** none external; imports `state_sync`, `identity`, `holder`.
- **Risks:** intake's body must reconcile with current write ordering (Q-004 —
  defer index-append until after push); the wrapper must roll back correctly on
  `StateConflictError` (the single most-tested unit). New intra-`core/skills`
  edge added (ADR-tracked).
- **Rollout:** feature-gated by `.klc/` being a `klc-state` worktree (no-op
  otherwise); backward-compatible; no migration of existing tickets.
- **Estimate:** M (12–16h).

## Option C — Event hooks on the lifecycle layer

Fire acquire/release/push from inside `core/skills/lifecycle.py`
(`set_state`/`apply_ack`/`advance_to_next`) so the verb files stay untouched.

- **Trade-off:** zero diff to the verbs, but buries network I/O inside the
  lowest-level pure state primitive, making it non-deterministic and breaking the
  "one push per verb" model (AC-5).
- **Affected files:** `core/skills/lifecycle.py`,
  `tests/integration/test_klc057_sync_holder.py`, plus regression churn across the
  large existing lifecycle test surface.
- **Affected public APIs:** `lifecycle.set_state` / `apply_ack` / `advance_to_next`
  gain hidden network side-effects (semantics changed though signatures stay).
- **New dependencies:** none external; imports `state_sync`, `identity`, `holder`.
- **Risks:** `set_state` is called for transient/intermediate states
  (src=core/skills/lifecycle.py:560-580) → would push on transient states,
  violating AC-5; AC-2 uniqueness-at-intake is not a state transition, so intake
  still needs bespoke wiring (abstraction does not even cover the ticket); hardest
  to keep an AC-8 no-op and the lifecycle test suite green.
- **Rollout:** feature-gated, but the no-op guarantee is the weakest of the three.
- **Estimate:** L (16–22h, mostly regression-fixing).

---

## Picked: Option B — shared `transaction` wrapper

Rationale (carried from discovery, re-affirmed by the scout): the
`pull → body → push-with-rollback` envelope is identical across all three verbs
and the CAS-rejection rollback is both the riskiest and the most test-worthy part.
It must not be triplicated (rules out A) nor hidden inside the pure state machine
(rules out C, which also fails to cover intake uniqueness). A single wrapper gives
one place for rollback, one place to short-circuit to a no-op when the feature is
off (C-004/AC-8), and a clean unit-test seam, while each verb keeps an explicit,
small body. The wrapper runs inside the existing per-ticket `acquire_lock` block,
satisfying C-003/AC-9 without new locking machinery.

## Decisions

> [!DECISION D-001] Picked Option B (shared `state_tx` wrapper) over A (inline)
> and C (lifecycle hooks). Reason: single rollback implementation + single no-op
> seam + unit-testable envelope. Recorded in ADR.

> [!DECISION D-002] Q-001 — CAS-rejection contract is **exception-based**:
> `state_sync.commit_and_push_cas` raises `StateConflictError` on same-ticket
> non-fast-forward (KLC-054 AC-4). The wrapper translates it to "already taken"
> (intake) or "concurrent update — retry" (ack/next). No sentinel return code.

> [!DECISION D-003] Q-002 — holder schema is a flat single object on the current
> phase: `meta.holder = {id, machine, since}`, cleared to `null` on release
> (KLC-056 AC-1/AC-4). Not a per-phase map. The board (KLC-060) / heartbeat
> (KLC-058) read this stable shape.

> [!DECISION D-004] Q-003 — feature detection = **`.klc/` is a git worktree bound
> to the `klc-state` branch** (no remote, no separate config flag).
> `state_feature.enabled()` returns True iff `git -C <klc_dir> symbolic-ref --short
> HEAD` == `klc-state` (equivalently `git worktree list` shows `.klc` on
> `klc-state`). Single detector, used by `state_tx` to short-circuit to a no-op
> (C-004/AC-8).

> [!DECISION D-005] Q-004 — intake rollback: build local `meta.json` + `raw.md`,
> **defer the global-index append until after** a successful CAS push; on
> `StateConflictError` roll back `meta.json`, `raw.md`, and the ticket dir. This
> keeps intake's meta/raw write order but guarantees "no orphan index entry" (AC-2)
> the cheap way — the append is the last, post-push step.

> [!DECISION D-006] `identity.current()` returns a **str** but
> `holder.acquire_holder`/`release_holder` take an identity **dict** `{id, machine}`
> (KLC-056 AC-8). The wrapper (consumer side) builds the dict:
> `{"id": identity.current(), "machine": socket.gethostname()}`. This adapter lives
> in `state_tx`, keeping the siblings decoupled.

## ASSUMPTIONS

> [!ASSUMPTION A-001] KLC-054/055/056 land before this ticket's build, exposing
> the import surface above. if-false=this ticket is blocked at build; the wiring
> contract here is the consumer spec those tickets must satisfy.

---

ADR_NEEDED=yes
