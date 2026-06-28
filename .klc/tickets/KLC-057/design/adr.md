---
ticket: KLC-057
adr: KLC-057-sync-holder-transaction-wrapper
status: accepted
date: 2026-06-27
authority: human
deciders: e_konchikov@wargaming.net
risk_tags: [data, migration]
---

# ADR — KLC-057: shared transaction wrapper for sync + holder wiring

## Context

KLC is being extended for serverless multi-user collaboration (KLC-053..060).
Lifecycle state lives in the same project repo on a `klc-state` **orphan branch**,
materialized as a git **worktree** at `.klc/`; `git push` of that branch to the
project's normal `origin` with CAS (non-fast-forward rejection) is the **only**
coordination primitive. This ticket (KLC-057) is the integration spine: it wraps the three
lifecycle verbs (`intake`, `ack`, `next`) so the primitives delivered by
KLC-054 (`state_sync`), KLC-055 (`identity`), and KLC-056 (`holder`) become live
behaviour — uniqueness at intake, holder lifecycle on the work verbs — while
staying a byte-for-byte no-op when the feature is unconfigured (single-user mode).

The dependency primitives are not yet in the tree. Their **specs** are the
authoritative contract, and this ADR pins the consumer-side integration points
the siblings are obligated to satisfy. Four design questions (Q-001..Q-004) gate
the design; this ADR closes all four.

ADR triggers met: new dependency edges added (verbs → three new skills, plus a
new intra-`core/skills` edge), a data/schema change written to shared state
(`meta.holder`), a public-API addition (`state_tx`, `state_feature`), and a
cross-collaborator persistence concern (CAS-pushed uniqueness/holder state).

## Decision

Adopt **Option B**: a single shared transaction wrapper,
`core/skills/state_tx.py`, that implements the
`pull → body → push-with-rollback` envelope once, plus a thin feature detector
`core/skills/state_feature.py`. Each verb supplies only its body and invokes the
wrapper **inside** its existing `with acquire_lock(ticket):` block.

```
with acquire_lock(ticket):              # existing per-ticket lock (C-003/AC-9)
    with state_tx(ticket, paths, msg) as tx:
        pull_rebase()                   # on enter; no-op if feature off
        # verb body: mutate .klc + holder
    # clean exit → commit_and_push_cas(paths, msg)  (pushes klc-state → origin)
    # StateConflictError → tx rolls back the local mutations
```

When `state_feature.enabled()` is False (`.klc/` is not a worktree bound to the
`klc-state` branch), `state_tx` is a pure pass-through: no pull, no push, no
holder writes — the verb behaves exactly as today (C-004/AC-8).

### Closing the open questions

- **Q-001 (D-002) — CAS-rejection contract: exception-based.**
  `state_sync.commit_and_push_cas(paths, msg, max_retries=3)` raises
  `StateConflictError` on a same-ticket non-fast-forward rejection (KLC-054 AC-4);
  it pushes the `klc-state` branch to `origin`, transparently rebases+retries
  other-ticket races (AC-3) and raises `RetryExhaustedError` past `max_retries`.
  `pull_rebase()` raises `RebaseConflictError` on a dirty rebase. The wrapper catches
  `StateConflictError` and surfaces it as **"already taken"** (intake) or
  **"concurrent update — retry"** (ack/next). No sentinel return codes.

- **Q-002 (D-003) — holder schema: flat single object on the current phase.**
  `meta.holder = {"id": <email>, "machine": <hostname>, "since": <iso8601-utc>}`,
  cleared to `null` by release (KLC-056 AC-1/AC-4). Not a per-phase map — the
  current phase has at most one holder. This is the stable shape KLC-058
  (heartbeat) and KLC-060 (board) read.

- **Q-003 (D-004) — feature detection: `.klc/` is a `klc-state` worktree.**
  `state_feature.enabled()` returns True iff `.klc/` is a git worktree bound to
  the `klc-state` branch — checked via `git -C <klc_dir> symbolic-ref --short HEAD`
  == `klc-state` (equivalently `git worktree list` showing `.klc` on `klc-state`).
  There is no remote named `klc-state` and no separate config flag — one detector,
  used by `state_tx`. KLC-053 `klc state init` is what creates the orphan branch +
  worktree, so the worktree binding is the single source of truth and avoids a
  config/state desync.

- **Q-004 (D-005) — intake rollback: defer index-append until after CAS push.**
  Intake writes `meta.json` + `raw.md` locally (unchanged order), runs the CAS
  push of those paths, and only **after** a successful push appends the entry to
  the append-only global tickets index. On `StateConflictError` the wrapper rolls
  back `meta.json`, `raw.md`, and the ticket dir; because the index append is the
  last post-push step, a rejected push leaves **zero** index pollution (AC-2's
  "no orphan index entry" without scanning/un-appending the index).

- **D-006 — identity str→dict adapter.** `identity.current()` returns a string,
  but `holder.acquire_holder`/`release_holder` take a dict `{id, machine}`
  (KLC-056 AC-8). The wrapper builds it consumer-side:
  `{"id": identity.current(), "machine": socket.gethostname()}`. This keeps
  KLC-055 and KLC-056 decoupled and confines the glue to KLC-057.

### Per-verb bodies

- **intake:** `state_tx` body = build local meta/raw → `acquire_holder(ticket, id)`
  on the first phase → push (`meta.json`, `raw.md`). The uniqueness guarantee
  *is* the CAS push: a key already created by a peer rejects as `StateConflictError`
  → "already taken" + rollback. Index-append is post-push.
- **ack:** `state_tx` body = existing validation/gate-policy → `apply_ack` advance
  → `release_holder(ticket, id)` for the phase just left → push. Release happens
  **after** advance and **before** push so one CAS push carries both (AC-5).
- **next:** `state_tx` body = `advance_to_next` → first-grab
  `acquire_holder(ticket, id)` for the entered phase → push. If the phase is held
  by another, `acquire_holder` raises `HolderConflictError` → "held by <id>",
  no steal (stealing is KLC-058).

## Consequences

Positive:
- The fragile CAS-rejection rollback exists exactly once and is unit-testable in
  isolation (`tests/test_state_tx.py`) against a local bare-repo fixture (AC-10).
- One seam guarantees the AC-8 no-op; single-user mode and all existing verb tests
  are untouched.
- Verb diffs stay small and explicit; gate-policy (KLC-045) is reused, not replaced
  (C-005).

Negative / risks:
- Two new `core/skills` modules and new import edges (verbs → skills; `state_tx` →
  `state_sync`/`identity`/`holder`). Accepted: edges follow the existing
  verb→skills direction; no cycle.
- Hard dependency on KLC-054/055/056 landing first (A-001). If a sibling deviates
  from the pinned contract, this ticket's build is blocked until reconciled — the
  contract here is the obligation.
- `meta.holder` is written to shared state across collaborators (risk_tags: data,
  migration). Mitigated by single-writer-per-ticket (C-003) + the rollback path.

## Alternatives considered

- **Option A (inline in each verb)** — rejected: triplicates the rollback path and
  the no-op short-circuit (3× AC-8 regression surface), not independently testable.
- **Option C (lifecycle hooks)** — rejected: buries network I/O in the pure state
  primitive (non-deterministic, pushes on transient states → breaks AC-5), and
  intake uniqueness is not a state transition so it would not even cover the ticket.
