---
ticket: KLC-021
kind: feature
authority: human
last_generated: 2026-06-05
risk_tags: [user-facing]
---

# KLC-021 — Jira integration: managed mode + push

## Goals

Add interactive state sync (klc→Jira) with the core principle: **choice at
the decision point, inline — never deferred**. Introduce `mode: managed`
where the lifecycle hook detects divergence at ack/next and prompts the
human in the same command. Part 2 of 3. Depends on KLC-020.

## Problem / Context

KLC-020 built read-only foundation. Today the hook at `lifecycle.py:137`
auto-pushes on every set_state ([!FACT src=core/skills/lifecycle.py:137]).
In managed projects the PM also moves Jira manually, so blind auto-push
races with them. We need: mirror keeps auto-push; managed makes the hook
interactive (detect → ask inline). Deferred "pending sync" is rejected —
it gets forgotten.

[!DECISION D-001] Only ack/next prompt. `klc jira status` stays read-only (KLC-020).
[!DECISION D-002] Non-TTY (CI) in managed at divergence → default "record
divergence, don't touch Jira" + stderr warning. NEVER push silently.
[!DECISION D-003] `sync` only reports + links + meta. State change ONLY via
explicit `reconcile`. No magic auto-resolution.
[!DECISION D-004] "moved by klc" comment on every klc-initiated transition.

## Acceptance Criteria

1. AC-1: `config/jira.yml` gains `mode: mirror|managed` and optional
   `managed_tickets: [KEY]`. validate_config + doctor pass.
2. AC-2: `jira_sync.build_plan(ticket) -> SyncPlan` — side-effect-free.
   Compares klc phase vs Jira status via status_mapping; lists target status,
   transition needed, conflicts. No network writes.
3. AC-3: `jira_sync.push(ticket) -> Result` — moves Jira to match klc phase,
   single-hop only. No direct transition → record conflict
   `transition-blocked`, show manual action, never move klc.
4. AC-4: `lifecycle.push_phase` is mode-aware:
   - mirror → auto-push as today (unchanged regression-tested);
   - managed + TTY, klc moved → prompt: 1) push Jira to match (recommended)
     2) leave as-is;
   - managed + TTY, PM moved Jira manually (current != last_jira_status AND
     != target) → CONFLICT prompt: 1) push Jira back (klc wins) 2) keep Jira,
     record divergence 3) skip — write [!CONFLICT] to meta, show in doctor;
   - managed + non-TTY → record divergence, no Jira write, stderr warning.
5. AC-5: `klc jira sync <KEY> --dry-run|--apply` — reports mismatch, adds/updates
   idempotent artefact links, updates meta.json:jira_sync. Does NOT change phase
   state.
6. AC-6: `klc jira reconcile <KEY> push` — explicit push entry point for when
   the human is not at ack.
7. AC-7: meta.json:jira_sync block written:
   `{enabled, issue_key, last_synced_at, last_jira_status,
   last_klc_phase (FULL phase:state), last_action, conflicts:[...]}`.
   conflict types: jira-moved-externally | transition-blocked | required-field |
   issue-missing.
8. AC-8: `klc doctor` surfaces meta.jira_sync.conflicts.

## Non-goals

- pull / force-pull (KLC-022).
- AC sync, create_missing_issue, multi-hop (deferred).

## Affected modules

- `config/jira.yml`, `core/skills/validate_config.py`
- `core/skills/jira_sync.py` — build_plan, push, mode-aware push_phase
- `core/skills/lifecycle.py` — push_phase hook becomes interactive
- `core/phases/jira.py` — sync, reconcile push subcommands
- `core/phases/doctor.py` — conflict surfacing
- `tests/integration/` — mirror vs managed, TTY/non-TTY, conflict detection
- `docs/process.md` — managed mode, sync vs reconcile

## Open questions

None blocking. TTY detection via `sys.stdin.isatty()`.

## Estimate

- complexity: 3 (interactive hook with TTY/non-TTY branches, mode logic)
- uncertainty: 2 (lifecycle hook touch; prompt UX in a hot path)
- risk: 2 (touches lifecycle.set_state — every transition path)
- manual: 1 (verify prompts against real Jira)
- total: 8 → **M**
