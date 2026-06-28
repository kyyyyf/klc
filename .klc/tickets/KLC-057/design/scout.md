---
ticket: KLC-057
agent: design-scout (performed inline by design agent)
last_generated: 2026-06-27
trigger: estimate.uncertainty=2 (>=2)
---

# Deep-context scout — KLC-057

Advisory pre-analysis consumed by `design/options.md` and `adr.md`. The
dependency primitives are unbuilt, so the scout's job here is to **pin the
import surface from the sibling specs/impl-plans** (the authoritative source
for the contract this ticket consumes) and confirm the verb seams.

## confirmed_files

Verb seams (the three files this ticket wraps):

- `core/phases/intake.py` — `run()` builds local artifacts then appends to the
  global index. src=core/phases/intake.py:129-260 verified=2026-06-27.
  Index-append is at intake.py:232-241 (the rollback-granularity hotspot, Q-004).
  Identity today via private `_git_user()` at intake.py:77-87 (KLC-055 replaces it).
- `core/phases/ack.py` — `run()` does ack inside `with acquire_lock(...)`, calls
  gate-policy at ack.py:170-191, then `_lc.apply_ack(...)`. src=core/phases/ack.py:49-220
  verified=2026-06-27. This is the integration precedent (import a skill, call it
  inside the verb).
- `core/phases/next.py` — `run()` does `_lc.advance_to_next(...)` inside
  `with acquire_lock(...)`. src=core/phases/next.py:35-109 verified=2026-06-27.

Lifecycle + paths the wrapper composes with (verified to exist today):

- `lifecycle.read_meta(ticket) -> dict` (lifecycle.py:95), `lifecycle.write_meta(ticket, meta)` (lifecycle.py:107).
- `lifecycle.current_state` (114), `lifecycle.apply_ack` (522), `lifecycle.advance_to_next` (470).
- `artefacts.acquire_lock(ticket)` context manager (artefacts.py:72), `LockedError` (49).
- `_paths.klc_dir() -> Path` (\_paths.py:43), `_paths.klc_global_tickets_index()` (102),
  `_paths.klc_ticket_dir/meta_file/raw_file`.

## dependency_impact

`depgraph.json` is **absent** from `.klc/index/` (verified: `ls` no match).
modules.json carries no dependency edges (meta.blast_radius.available=false).
So edge analysis falls back to direct source reading + grep findReferences:

- **Downstream (consumed) — not in tree yet** (KLC-054/055/056 deliver them):
  - `state_sync.pull_rebase(klc_dir)`, `state_sync.commit_and_push_cas(paths, msg, ticket, klc_dir, remote, max_retries)`,
    and exceptions `StateConflictError` / `RebaseConflictError` / `RetryExhaustedError` / `ConfigError`.
    Source of truth: KLC-054 spec AC-1..AC-5 + impl-plan step-1/step-2 Interfaces.
  - `identity.current() -> str` (email/name/$USER, SystemExit if unset). Source: KLC-055 spec AC-1/AC-2.
  - `holder.acquire_holder(ticket, identity)` / `holder.release_holder(ticket, identity)` where
    `identity` is a dict `{id, machine}`; stored shape `meta.holder = {id, machine, since}`;
    raises `HolderConflictError`. Source: KLC-056 spec AC-1..AC-8.
- **Upstream (dependents):** the three verbs are dispatched by `scripts/klc`
  `_run_phase` (src=scripts/klc:90-93,123 per spec). No other module imports the
  verb `run()` functions directly (grep over core/,scripts/ — verbs are CLI leaves).
- **New edges this ticket adds:** `core/phases/{intake,ack,next}` → `core/skills/{state_sync,identity,holder}`
  and → a new `core/skills/state_tx` wrapper. These are new import edges (not in
  any depgraph because none exists) and a new `core/skills` → `core/skills` edge
  (`state_tx` → `state_sync`/`identity`/`holder`). Flagged in options Risks; trips ADR.

## open_questions

All four spec questions are **closeable now** from the sibling specs (no need to
wait for the siblings to build — their specs are the contract). Resolutions:

- Q-001 → exception-based: `commit_and_push_cas` **raises** `StateConflictError`
  on same-ticket CAS rejection (KLC-054 AC-4). No sentinel return code.
- Q-002 → flat single-object `meta.holder = {id, machine, since}` on the current
  phase, cleared to `null` on release (KLC-056 AC-1/AC-4).
- Q-003 → feature = presence of a `klc-state` git remote; no separate config flag.
- Q-004 → build local meta/raw, **defer global-index append until after** a
  successful CAS push; on `StateConflictError` roll back meta/raw and the ticket dir.

One residual contract gap, decided in the ADR (D-005): `identity.current()`
returns a **str** but `holder.acquire_holder` wants a dict `{id, machine}` — the
wrapper builds the dict from the email + hostname.

## recommended_option_shape (advisory)

Spec already picked **Option B (shared `transaction` wrapper)**. The scout
concurs: the rollback path is the single riskiest element and must exist once.
Recommended seam: a `core/skills/state_tx.py` context manager invoked **inside**
each verb's existing `acquire_lock` block, short-circuiting to a pure no-op when
no `klc-state` remote is present (C-004/AC-8).
