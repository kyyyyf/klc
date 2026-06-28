---
ticket: KLC-056
kind: feature
authority: agent
track: S
risk_tags: [data]
---

## Goals
Add a `holder` sub-object to `meta.json` on the current phase so that `acquire_holder()` claims a free phase (first-grab semantics) and `release_holder()` clears it, giving the multi-user coordination layer a pure-logic, git-transaction-free ownership primitive.

## Acceptance Criteria
- [ ] AC-1: `acquire_holder(ticket, identity)` writes `meta.holder = {id, machine, since}` when `meta.holder` is absent or null, and returns the holder dict.
- [ ] AC-2: `acquire_holder(ticket, identity)` raises `HolderConflictError` (with the existing holder's id and since in the exception) when `meta.holder` is already set to a different identity id.
- [ ] AC-3: `acquire_holder(ticket, identity)` is idempotent: if the caller already holds the phase (same id), it returns the existing holder dict without overwriting `since`.
- [ ] AC-4: `release_holder(ticket, identity)` sets `meta.holder` to null when the caller is the current holder, and returns True.
- [ ] AC-5: `release_holder(ticket, identity)` raises `HolderConflictError` when a different identity holds the phase, and leaves `meta.holder` unchanged.
- [ ] AC-6: `release_holder(ticket, identity)` is a no-op (returns False) when `meta.holder` is already null.
- [ ] AC-7: Both functions depend solely on `lifecycle.read_meta` / `lifecycle.write_meta` — no direct filesystem I/O and no git operations are performed inside `holder.py`.
- [ ] AC-8: `identity` parameter is a dict with at least `{id: str, machine: str}`; `since` in the stored holder is an ISO-8601 UTC timestamp set at acquire time.

## Affected
holder: core/skills/holder.py (new file) [!ASSUMPTION if-false=scope-may-expand — file does not exist yet; path chosen to match the `core/skills/` convention used by all peer modules]
lifecycle: lifecycle.read_meta / lifecycle.write_meta, src=/home/ek/projects/klc/core/skills/lifecycle.py:95 — read/write interface consumed by holder.py
[!ASSUMPTION if-false=scope-may-expand] identity (KLC-055) — identity.current() supplies the `identity` dict; not yet implemented, holder.py accepts a plain dict so it is decoupled from identity at this layer

## Estimate
complexity: 1
uncertainty: 1
risk: 1
manual: 0
total: 3

DISCOVERY_LITE_DONE
