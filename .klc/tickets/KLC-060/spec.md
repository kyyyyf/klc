---
ticket: KLC-060
kind: feature
authority: human
last_generated: 2026-06-27T00:00:00Z
risk_tags: [user-facing]
---

# KLC-060 — Surface holder + "waiting on ack" in `klc board` and `klc status`

## Goals

Make the current-phase **holder** visible in the two read surfaces a user
checks first — `klc board` (cross-ticket kanban) and `klc status <ticket>`
(per-ticket path) — and add a "waiting on ack from `<id>`" hint when a ticket
sits in `ack-needed`. Purely derived from `meta.json`; no new persisted state,
no writes, no git, no forge API.

## Problem / Context

In the multi-user model (KLC-053..059) a phase is grabbed by one person via the
per-phase `holder` field on `meta.json`. Today neither read surface shows who
holds a phase, so a second user cannot tell a ticket is already being worked,
nor who they are waiting on to ack. KLC-060 closes that visibility gap with a
read-only display layer.

FACT: `klc board` today projects only `{key, track, kind}` from each
`meta.json` and groups by `phase`; it never reads a holder field.
src=core/phases/board.py:33-37 verified=2026-06-27

FACT: `klc status` renders the current phase via `_annotate_current(phase,
state, meta)` and already branches on phase state; `ack-needed` is its own
branch (line 139-143). It does not mention any holder.
src=core/phases/status.py:117-118,129-146 verified=2026-06-27

FACT: The phase-state vocabulary is `work | ack-needed | ack`; "waiting on an
ack" is exactly the `ack-needed` state. src=core/skills/phases.py:37-40
verified=2026-06-27

FACT: The `holder` field does **not** yet exist anywhere in code or in any
`meta.json`; a word-boundary grep for `holder` over `core/` and `scripts/`
returns no hits, and no ticket `meta.json` contains a `"holder"` key.
src=grep -rnw holder core/ scripts/ (empty) verified=2026-06-27

ASSUMPTION: The holder shape is `holder: {id, machine, since}` attached to the
current phase, as specified by the KLC-060 dependency KLC-056.
src=.klc/tickets/KLC-056/raw.md verified=2026-06-27
if-false: the field name / sub-keys read by the display code change; the
display code is a thin projection and adjusts in one place each (board.py
projection, status.py annotation).

## Acceptance Criteria

1. AC-1: Given a ticket whose `meta.json` carries a current-phase `holder` with
   an `id`, when the user runs `klc board` (text and `--json`), then that
   ticket's row/record surfaces the holder id; given a ticket with **no**
   holder, the row renders unchanged from today (no crash, no empty artifact).
2. AC-2: Given a ticket in `ack-needed` whose current phase has a `holder`,
   when the user runs `klc status <ticket>`, then the current-phase annotation
   includes `waiting on ack from <id>`; given any other state, the holder (when
   present) is shown but the "waiting on ack" wording is omitted.
3. AC-3: Both commands are strictly read-only — they read `meta.json` and write
   nothing; a missing/null `holder` is tolerated everywhere (no `KeyError`,
   `--json` stays valid JSON).

## Non-goals

- Acquiring, releasing, refreshing, or stealing a holder (KLC-056 / KLC-058).
- Any git sync, push, or CAS (KLC-053/054/057).
- A `klc remind` reminder surface (KLC-059).
- Resolving `<id>` to a display name or registry (KLC-055 keeps id == git
  identity; no registry).

## Constraints

> [!CONSTRAINT C-001] source=raw.md
> Read-only and derived: no new persisted state, no writes to `meta.json`,
> no git, no forge API. Display purely from existing `meta.json`.

> [!CONSTRAINT C-002] source=core/phases/board.py:33-37, status.py:129-146
> Holder absence must be tolerated identically to today's behaviour: when no
> `holder` key is present, both surfaces render exactly as they do now. This
> matters because KLC-056 (which writes the field) is not yet built, so most
> live tickets have no holder during rollout.

## Affected modules

- core/phases: both read commands live here (`board.py`, `status.py`); this is
  the only module touched. Name from modules.json (path `core/phases`).

## Open questions

_None blocking._ The holder field shape is specified by KLC-056 and the display
is a thin projection; if KLC-056 finalises a different field name, the two
projection points adjust trivially (captured as the ASSUMPTION above, not a
blocker).

## Approaches (detail in design/options.md)

- Option A — Inline projection in each command: read `holder` directly in
  `board.py` and `status.py` where meta is already in hand.
- Option B — Shared `holder_display` helper in a skill: one formatter
  (`holder_label(meta)` / `waiting_hint(meta, state)`) imported by both.

Picked: Option B — a tiny shared `holder_display` helper — because two surfaces
must format the same "holder / waiting-on-ack" string identically and tolerate
the same null cases; one tested helper keeps the wording and the KLC-056
field-shape coupling in a single place, which directly serves C-002.

## Estimate
- complexity: 0
- uncertainty: 1
- risk: 0
- manual: 0
- total: 1
- track: XS

> [!NOTE] Track downgrade M→XS. route_hint=M (intake keyword heuristic).
> This is a read-only display layer over an existing meta dict in a single
> module (`core/phases`), with a specified upstream contract (KLC-056) — a
> genuine XS. Blast-radius graph is **unavailable**: `.klc/index/modules.json`
> carries no `depended_by` reverse edges, so the strict downgrade evidence
> ("all dependents known AND no external dependents") cannot be mechanically
> proven. The downgrade is recommended on proportionality grounds; if
> `can_complete_discovery` blocks it on the missing-blast-radius rule, the
> operator should clear it with `klc retrack KLC-060 XS`.
