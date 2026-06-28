---
ticket: KLC-060
authority: hybrid
last_generated: 2026-06-27T09:00:00Z
---

# Design — KLC-060

Surface the current-phase `holder` and a "waiting on ack from `<id>`" hint in
`klc board` and `klc status`, derived read-only from `meta.json`. Picked
approach: **Option B** — one shared `holder_display` helper under `core/skills`
imported by both surfaces, so the wording and the KLC-056 field-shape coupling
live in a single tested place (serves constraint C-002).

## Decision summary

- **D-001**: Formatting lives in a new helper `core/skills/holder_display.py`
  exposing two pure functions — `holder_label(meta)` and
  `waiting_hint(meta, state)` — rather than inline in each command. Rationale:
  identical null-tolerance and identical wording on two surfaces (C-002); one
  test target; the KLC-056 field shape (`holder.id`) is referenced in exactly
  one module.
- **D-002**: Board `--json` carries the holder as a `holder_id` key that is
  **omitted** (not `null`) when no holder is present, so existing consumers are
  unaffected (test-plan regression row; edge case "never appear as None").
- **D-003**: Both functions return `None` for every degraded case (no `holder`
  key, `holder` present but no `id`, empty-string `id`). Callers treat `None`
  as "render exactly as today" — this is the single guard for AC-3 / C-002.

## Dependency impact

`.klc/index/depgraph.json` is **unavailable** (file absent;
`dependency-impact: unavailable (no depgraph.json; modules.json carries no
reverse edges)`). Fell back to reading the call sites directly and verifying
the touched symbols by source inspection (LSP-equivalent grounding below).

- **New module `holder_display`**: has **no** dependents (it does not exist
  yet) — it adds two *new* outbound edges: `board.py → holder_display` and
  `status.py → holder_display`. Both are within the single affected module
  `core/phases` importing from `core/skills`, the existing import direction
  used throughout (`board.py` and `status.py` already
  `sys.path.insert` the skills dir and import `_paths`, `lifecycle`,
  `phases`). No edge is inverted; no cycle is created (skills do not import
  phases).
- **Downstream of the touched files**: `board.py` imports `_paths`;
  `status.py` imports `_paths`, `lifecycle`, `phases`. None of these change.
- **Upstream (dependents) of the touched files**: `board.py` and `status.py`
  are CLI entry points dispatched by `scripts/klc`; nothing imports them as
  libraries (no `import board` / `import status` anywhere under `tests/` or
  `core/`). The change is additive to their output only.

Verified symbols (source-grounded):

- FACT `board.py` projects `{key, track, kind}` per ticket and groups by
  `phase`. src=core/phases/board.py:33-37 verified=2026-06-27
- FACT `status.py` renders the current phase via
  `_annotate_current(p, cur_state, meta)`; the `ack-needed` branch is
  `state == _ph.STATE_ACK_NEEDED`. src=core/phases/status.py:117,129,139
  verified=2026-06-27
- FACT phase-state constants: `STATE_WORK="work"`,
  `STATE_ACK_NEEDED="ack-needed"`, `STATE_ACK="ack"`.
  src=core/skills/phases.py:37-40 verified=2026-06-27
- FACT no `holder` symbol exists in `core/` today (grep empty), so adding the
  helper introduces a new contract, not a change to an existing one.
  src=grep -rnw holder core/ (empty) verified=2026-06-27

The new edges (`board.py`/`status.py` → `holder_display`) are additive,
same-direction, low-coupling, and stay inside the one declared affected module
boundary. They do **not** trigger the ADR check (no boundary crossed, no edge
inverted, no external dep, no schema change, no public-API change to an
existing symbol).

## Symbol references for build

- New: `holder_display.holder_label(meta: dict) -> str | None`
- New: `holder_display.waiting_hint(meta: dict, state: str) -> str | None`
- Reused, unchanged: `_ph.STATE_ACK_NEEDED` (status.py already imports
  `phases as _ph`).

## Tests

See `test-plan.md`. Two acceptance suites
(`tests/integration/test_board_holder.py`,
`tests/integration/test_status_holder.py`) drive the public CLI entry points
(`scripts/klc board`, `scripts/klc status`) via subprocess with `PROJECT_ROOT`
pointed at a temp `.klc`, matching the existing integration harness
(`tests/integration/test_retrack.py`). The negative / fail-closed rows
(holder absent → unchanged, no `KeyError`, `--json` still valid) are the
acceptance signal for AC-3 / C-002 and are written before the wiring.

## Track / proportionality

Genuine XS (read-only display, single module, specified upstream contract).
The plan is 3 one-commit steps: helper + RED tests, wire board, wire status.
