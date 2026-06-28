---
ticket: KLC-057
phase: design
authority: human
last_generated: 2026-06-27
picked_option: B
adr: design/adr.md
---

# Design — KLC-057: wire sync + holder into intake/ack/next

## Summary

Adopt **Option B** (picked at discovery, re-affirmed): a single shared
transaction wrapper `core/skills/state_tx.py` that does
`pull → body → push-with-rollback` once, plus a feature detector
`core/skills/state_feature.py`. Each verb (`intake`/`ack`/`next`) supplies only
its body and calls the wrapper **inside** its existing `acquire_lock(ticket)`
block. When `.klc/` is not a worktree bound to the `klc-state` branch, the
wrapper is a pure no-op so single-user behaviour is byte-for-byte unchanged
(AC-8). Full rationale and contract in `design/adr.md`; trade-offs in
`design/options.md`.

## Closed design questions

| Q | Decision | Item |
|---|----------|------|
| Q-001 exception/return contract of `commit_and_push_cas` | Exception-based: raises `StateConflictError` on same-ticket non-fast-forward (KLC-054 AC-4); no sentinel return code. Wrapper maps it to "already taken"/"concurrent update". | D-002 |
| Q-002 holder schema in meta.json | Flat single object on the current phase: `meta.holder = {id, machine, since}`, cleared to `null` on release (KLC-056). Not a per-phase map. | D-003 |
| Q-003 feature detection | `.klc/` is a git worktree bound to the `klc-state` branch (`git -C <klc_dir> symbolic-ref --short HEAD` == `klc-state`); no remote, no separate config flag. `state_feature.enabled()`. | D-004 |
| Q-004 intake rollback granularity | Build local meta/raw, **defer global-index append until after** a successful CAS push; roll back meta/raw + ticket dir on `StateConflictError`. | D-005 |
| (extra) identity str vs holder dict | Wrapper builds `{id: identity.current(), machine: hostname}` consumer-side. | D-006 |

## Consumer contract (pinned from sibling specs — the obligation those tickets satisfy)

- `state_sync.pull_rebase() -> None` — runs `git pull --rebase` in `.klc/`; raises `RebaseConflictError`.
- `state_sync.commit_and_push_cas(paths, msg, max_retries=3) -> None`
  — stages/commits `paths` and pushes the `klc-state` branch to `origin` (the
  worktree's upstream); raises `StateConflictError` (same-ticket), `RetryExhaustedError`, `ConfigError`.
- `identity.current() -> str`.
- `holder.acquire_holder(ticket, identity_dict) -> dict` — raises `HolderConflictError`.
- `holder.release_holder(ticket, identity_dict) -> bool`.

## New public surface this ticket adds (core/skills)

- `state_feature.enabled() -> bool` — True iff `.klc/` is a git worktree bound to the `klc-state` branch.
- `state_tx(ticket, paths, msg)` — context manager: pull on enter, push on clean
  exit, roll back local mutations on `StateConflictError`; pure no-op when the
  feature is off.

## Where the wrapper plugs into each verb (seams verified today)

- intake — body after the meta/raw write, index-append moved post-push. src=core/phases/intake.py:182-241
- ack — body around the existing gate-policy + `apply_ack`. src=core/phases/ack.py:64,170-191
- next — body around `advance_to_next`. src=core/phases/next.py:46,78

See `design/impl-plan.md` for the TDD step sequence.
