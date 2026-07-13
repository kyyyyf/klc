---
ticket: KLC-058
kind: build-log
---

# Build log — KLC-058

Built in an isolated worktree by a build sub-orchestrator, strict TDD
(test-only RED commit then impl GREEN commit per step). Branch
`feature/klc-058-steal-heartbeat`, rebased onto current main.

## Step 1 — 2026-07-13
**Attempt**: `heartbeat_holder(ticket)` in `core/skills/holder.py` — updates
`meta.holder.heartbeat_at` to now (ISO-8601 UTC `...Z`), preserving all other
fields; raises `ValueError` when no holder present (AC-2). Placed in holder.py
(not lifecycle.py per spec) alongside KLC-056's acquire/release, reusing
`_now`/`_validate_identity`/`_existing_holder` — documented scope adjustment.
**Outcome**: green
**Notes**: RED commit `eaf99ba` (tests only) failed `AttributeError: no
heartbeat_holder`; GREEN commit `167db12`.

## Evidence

```
$ python3 -m pytest tests/test_holder_steal.py -k heartbeat -q
6 passed
```

## Step 2 — 2026-07-13
**Attempt**: `steal_holder(ticket, identity, ttl)` + `HolderActiveError` +
`HOLDER_TTL_SECONDS=30*60` in holder.py; `core/phases/steal.py` `run(argv)`
(`klc steal <KEY>`, `--ttl-minutes` override); `"steal"` registered in
`scripts/klc` LIFECYCLE_CMDS. Age from `heartbeat_at` else `since`; within TTL
→ non-zero exit + clear message + holder unchanged; expired → warning-before-
takeover (via `on_takeover` callback, keeping the skill print-free) + overwrite
(AC-1). Stealer identity `{id: identity.current(), machine: gethostname()}`.
Operation wrapped in `artefacts.acquire_lock` (stale-PID auto-reclaim).
**Outcome**: green
**Notes**: RED commit `fce9531`; GREEN commit `72952f8`. End-to-end dispatcher
drive verified: stale holder → `STOLEN` rc=0 + warning; active holder →
`refusing to steal` rc=1.

## Evidence

```
$ python3 -m pytest tests/test_holder_steal.py -q
22 passed
$ python3 -m pytest tests/test_holder.py -q
20 passed
$ python3 -m pytest tests/ -k "steal or heartbeat" -q --ignore=tests/fixtures
22 passed, 587 deselected
```
