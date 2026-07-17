---
ticket: KLC-064
phase: design
authority: hybrid
last_generated: 2026-07-16
picked_option: A1+B1
adr: design/adr.md
depends_on: [KLC-061]
constrained_by: [KLC-062]
---

# Design — KLC-064: wire heartbeat_holder as a throttled, feature-ON writer

## Summary

Add a `klc heartbeat` verb, driven by a non-blocking UserPromptSubmit hook, that
refreshes an actively-held ticket's `meta.holder.heartbeat_at` and propagates it
to the shared `klc-state` branch — but **throttled** to at most once per
`HOLDER_TTL_SECONDS // 3` per held ticket, and **only under feature-ON** (nobody
steals in single-user mode). Within the throttle window the command is a pure
read-only no-op, so it adds no per-prompt tracked-tree churn (KLC-062). The
write+push reuses the `state_tx` holder-mutation envelope that KLC-061
establishes for `steal` — no bare out-of-`state_tx` write. Full rationale in
`design/adr.md`; trade-offs in `design/options.md`.

## Where heartbeat_at and the throttle marker live

`heartbeat_at` lives in the CAS-pushed `meta.holder` — the only place a remote
peer's `steal_holder` reads liveness from. Because we write it ONLY when we push,
that same field doubles as the "last-pushed" throttle marker; no separate marker
file is introduced (options A2/A3 rejected).

## Control flow (feature-ON)

```text
klc heartbeat  (per UserPromptSubmit, best-effort, always exit 0)
  └─ if not state_feature.enabled():           return 0     # feature-OFF no-op
  └─ meta = read-only meta probe (KLC-062 read; no migration write)
  └─ h = meta.holder;  require h held-by-me AND phase endswith ":work"  else return 0
  └─ last = h.heartbeat_at or h.since
  └─ if age(last) < HOLDER_TTL_SECONDS // 3:    return 0     # throttled no-op (no write/push)
  └─ with acquire_lock(ticket):                             # window elapsed → propagate once
        with state_tx(ticket, f"heartbeat {ticket}") as tx: # KLC-061 envelope: pull → body → CAS-push
            if tx is not None:
                holder.heartbeat_holder(ticket)              # writes heartbeat_at; glob-committed + pushed
  └─ (all wrapped in try/except → swallow, return 0)
```

Feature-OFF: the first guard returns 0 before any read → `meta.json` byte-identical.

## New / changed surface

- `core/skills/holder.py`: add `HEARTBEAT_PUSH_INTERVAL_SECONDS = HOLDER_TTL_SECONDS // 3`
  beside `HOLDER_TTL_SECONDS` (src=core/skills/holder.py:69). `heartbeat_holder`
  (src=:162) is unchanged.
- `core/phases/heartbeat.py` (NEW): `run(argv) -> int`, always 0. Resolves identity
  non-raising (same order as `remind._git_user`), scans identity-held `:work`
  tickets, applies the throttle, and propagates via `state_tx`.
- `scripts/klc`: `"heartbeat"` added to `LIFECYCLE_CMDS` (src=:92) and
  `NO_DRAIN_CMDS` (src=:107).
- `klc-plugin/hooks/heartbeat.py` (NEW) + a third `UserPromptSubmit` block in
  `klc-plugin/hooks/hooks.json` — mirrors `remind.py`, silent, exit 0.
- Docstrings in `core/phases/steal.py:5` and `core/skills/holder.py` updated to
  name the real driver.

## Consumer contract reused (must exist via KLC-061)

- `state_tx(ticket, msg)` context manager — yields a truthy handle feature-ON,
  `None` feature-OFF; pull → body → glob-commit + CAS-push; subtree rollback on
  failure. src=core/skills/state_tx.py verified=2026-07-16.
- `state_feature.enabled() -> bool`. src=core/skills/state_feature.py:39.
- `holder.heartbeat_holder(ticket) -> dict` (writes `heartbeat_at`, preserves
  siblings, raises `ValueError` on absent holder). src=core/skills/holder.py:162.
- `holder.steal_holder(...)` TTL gate — the consumer that reads `heartbeat_at`.
  src=core/skills/holder.py:222.

## Closed design questions

| Q | Decision | Item |
|---|----------|------|
| Q-001 where the last-pushed marker lives | `heartbeat_at` in CAS-pushed `meta.holder` is the marker (written only on push). | D-1 |
| throttle window | `HOLDER_TTL_SECONDS // 3` (3× margin below steal TTL; ≤3 pushes/TTL). | D-2 |
| per-prompt churn | read-only no-op within window; KLC-062 side-effect-free read. | D-3 |
| how it reaches origin | `state_tx` KLC-061 holder envelope, never a bare write. | D-4 |
| feature-OFF | hard no-op before any read; byte-parity. | D-5 |
| trigger | throttled UserPromptSubmit hook. | D-6 |

## Open (operator)

- Q-002: the ≤1-per-window prompt pays a synchronous git round-trip inside the
  hook timeout (~1-2 s). Keep the hook + throttle (recommended, reliable for the
  long-single-phase case), or restrict the push to explicit verb invocations?

See `impl-plan.md` for the TDD step sequence and `test-plan.md` for coverage
(incl. the AC-5 steal-vs-heartbeat property test on a real bare-repo fixture).
