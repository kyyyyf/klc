---
title: Framework refactor plan (KLC-006..009 + 003..005)
authority: human
last_updated: 2026-06-04
status: superseded-by-plan.md
---

# Framework refactor & optimization plan

> **Note (2026-06-04):** This document covers the original
> KLC-006..009 scope. The active improvement plan is now tracked in
> `plan.md` (KLC-011..017). See plan.md for the current phase map,
> discovery-lite routing, conditional phases, review cascade, and
> token telemetry work.

Cross-ticket coordination doc. Single source of truth for the order,
dependencies, and acceptance signals across KLC-003..009.

## Goal

Refactor and optimize the klc framework itself: docs, code, tests,
config. Each refactor change must go through the framework as a
ticket, so we exercise (and dogfood) the lifecycle while we improve
it.

## Tickets in scope

| Key      | Title                                  | Track | Est | Status            |
|----------|----------------------------------------|-------|-----|-------------------|
| KLC-003  | GitLab/GitHub publish adapters         | S     | 4   | intake:ack-needed |
| KLC-004  | C++ call graph (scip-clang)            | S     | 7   | intake:ack-needed |
| KLC-005  | TS call graph (TS Compiler API)        | S     | 6   | intake:ack-needed |
| KLC-006  | Documentation refactor                 | S     | 4   | intake:ack-needed |
| KLC-007  | Code refactoring (skills/phases/scripts) | M   | 7   | intake:ack-needed |
| KLC-008  | E2E fake-agent pipeline + unit tests   | S     | 5   | intake:ack-needed |
| KLC-009  | Config audit & cleanup                 | S/M   | 6   | intake:ack-needed |

## Order of execution

Decision (2026-05-28): split KLC-007 across phases; build runs after
docs settle.

```
1. KLC-008  ── full lifecycle (XS-fasttrack disabled — needs review)
              gives e2e safety net; unblocks every later ticket.

2. KLC-007  ── only intake → discovery (audit phase).
              Produces inventory: keep / merge / delete / move.
              No code changes yet. Pause here.

3. KLC-006  ── full lifecycle.
              Writes docs against the *target* state from 007.discovery,
              not the bloated current state.

4a. KLC-007 ── resume from acceptance-test-plan → build → archived.
4b. KLC-009 ── full lifecycle, parallel with 4a.
              Both protected by 008 e2e + smoke.

5. KLC-003  ── full lifecycle. Independent ticket.
              Can also slot in earlier if a quick win is needed.

6. KLC-004, KLC-005 ── after 1–5 land. Re-confirm gates first
              (do we still need C++ / TS call graph?).
```

## Lifecycle policy per ticket

Current policy (2026-06-04): **S-track uses discovery-lite** (see plan.md
Phase 2, KLC-013). XS-fasttrack for S-track is no longer the policy.

- M-track (KLC-007): **full lifecycle** — intake → discovery →
  acceptance-test-plan → build → review → integrate → observe →
  learn → archived.
- S-track (KLC-003, 004, 005, 006, 008, 009): intake → discovery →
  acceptance-test-plan → build → review → integrate → observe → learn.
  Once KLC-013 lands, S-track will use discovery-lite instead of
  full discovery.

## Dependencies

```
KLC-008 ──┐
          ├──> KLC-007 (build)
          └──> KLC-009

KLC-007 (discovery) ──> KLC-006 ──> KLC-007 (build)
                                ──> KLC-009 (uses doc structure)

KLC-003, KLC-004, KLC-005: independent
```

Hard blockers:
- KLC-007.build requires KLC-008 done
- KLC-009 requires KLC-008 done
- KLC-006 requires KLC-007.discovery done (so docs reflect target)

## Per-ticket success signal

- **KLC-008**: `python tests/e2e_pipeline.py` exits 0; covers all
  4 tracks; <60s runtime.
- **KLC-007 (discovery)**: `discovery.md` contains audit table for
  every file in `core/skills/`, `core/phases/`, `scripts/`.
- **KLC-006**: new contributor can run a ticket end-to-end using
  only `docs/`. `docs/phases/<phase>.md` exists for every phase.
- **KLC-007 (build)**: smoke + e2e + LSP tests pass. ≥10% LOC drop
  in `core/skills/`. No `.bak` files.
- **KLC-009**: `klc doctor` warns on unknown YAML keys. Config line
  count down ≥15%. `severity-rubric.md` moved to `docs/`.
- **KLC-003**: GitLab MR labels + comments posted on test MR.
  Adapters skip silently when tokens unset.
- **KLC-004 / KLC-005**: re-confirmation gate cleared first; then
  per-ticket ACs.

## Risks & mitigations

- **Risk**: 007.build breaks framework, blocks 006/009.
  **Mitigation**: 008 lands first. Roll back via `git revert` if
  smoke breaks.
- **Risk**: 006 docs drift from 007.build outcome.
  **Mitigation**: 006 cites the audit table from 007.discovery, not
  current code. 007.build follows that target.
- **Risk**: parallel 007.build ∥ 009 cause merge conflicts in same
  files.
  **Mitigation**: 007 owns `core/`, 009 owns `config/`. No overlap.
- **Risk**: refactor-tickets reveal framework bugs that block
  themselves.
  **Mitigation**: keep an `xs-build` escape hatch; if a blocker
  surfaces, file it as a new XS ticket and fix outside the chain.

## Tracking

Update this file when a ticket finishes a phase. Treat as a board.
The per-ticket `meta.json` is authoritative for state machine; this
file is the cross-ticket overview.

## Why "framework refactors itself through the framework"

User intent (2026-05-28): "хочу чтобы каждый тикет проходил через
процесс фрэймворка". Goals:

1. Dogfooding — running real refactor work through klc surfaces
   friction we wouldn't see in synthetic tests.
2. Regression detection — if 007 breaks intake, 008's lifecycle
   stalls; we catch it immediately.
3. Documentation generation — the artefacts produced by each
   ticket (spec, design, retro) become reference examples for
   docs/ in KLC-006.

## Related

- `MEMORY.md` → `project_refactor_plan.md` (older 6-milestone plan,
  superseded by this doc for KLC-006..009 scope)
- `PHASE4_PLAN.md` lines 89-161 (KLC-004, KLC-005 detailed plans)
- `PHASE3A_COMPLETE.md` line 132 (KLC-003 origin)
