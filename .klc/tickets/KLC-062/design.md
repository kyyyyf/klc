---
ticket: KLC-062
phase: design
authority: human
last_generated: 2026-07-16
picked_option: A
---

# Design — KLC-062: make `klc remind` (and `klc status`) truly read-only

## Summary

Adopt **Option A** (picked at discovery): make the completion probe and the
meta-read side-effect-*optional* via backward-compatible defaulted keywords,
rather than relocating persistence (Option B) or special-casing one verb
(Option C). Two independent write sites are the whole bug, and each is closed by
a keyword that defaults to today's behaviour:

- `phase_completion.can_complete(...)` gains `persist: bool = True`, threaded into
  `can_complete_discovery` / `can_complete_discovery_lite`. It guards the two
  write sites on those success paths: the `_sync_risk_tags(ticket)` call and the
  floor-guard `_lc.write_meta(...)` audit. The completability *decision* (incl.
  the downgrade-safety block) is unchanged; only the persistence is gated.
- `lifecycle.read_meta(...)` gains `persist_migration: bool = True`; a thin
  `read_meta_ro(ticket)` wrapper calls it with `persist_migration=False`. The
  in-memory legacy migration still runs (callers see the modern phase for
  display/logic); only the write-back to disk is suppressed.

Read-only callers pass the read-only forms: `remind` uses `read_meta_ro` +
`can_complete(..., persist=False)`; `status` uses `read_meta_ro`; the
`gate_policy` advisory probe uses `can_complete(..., persist=False)`. The `ack`
path keeps every default (`persist=True`, `read_meta`), so `risk_tags` and the
floor-guard audit still persist at the real transition (AC-3).

Rationale and rejected options are in `design/options.md`.

## Closed design questions

| Q | Decision | Notes |
|---|----------|-------|
| How to keep `can_complete` backward-compatible? | Keyword-only `persist: bool = True`; only the write sites are guarded, never the pass/fail decision. | C-002 — foundational API, defaulted so ack/CLI/all callers are unchanged. |
| Where does `risk_tags` persistence still happen? | At `ack.py:82` (manual-completion detection), which calls `can_complete(...)` with the default `persist=True`. | AC-3 — this is the correct completion transition. |
| How to suppress the legacy-migration write on read? | `read_meta(..., persist_migration=False)` + `read_meta_ro` wrapper; migration still applied in-memory for display. | C-003 / AC-2. |
| Should `board.py` change? | No functional change needed — it already uses raw `json.loads`. Optionally left as-is (reference discipline). | Non-goal to churn a correct file. |
| Does the floor-guard downgrade block still fire under `persist=False`? | Yes — `is_downgrade_safe` still runs and can still return `(False, ...)`; only the `write_meta` audit is skipped when `persist=False`. | The probe stays honest about completability. |

## Public surface changes (core/skills)

- `lifecycle.read_meta(ticket, *, persist_migration: bool = True) -> dict`
- `lifecycle.read_meta_ro(ticket) -> dict`  — `read_meta(ticket, persist_migration=False)`
- `phase_completion.can_complete(ticket, phase_id, *, persist: bool = True) -> tuple[bool, str]`
- `phase_completion.can_complete_discovery(ticket, *, persist: bool = True)`
- `phase_completion.can_complete_discovery_lite(ticket, *, persist: bool = True)`

## Where each seam plugs in (verified today)

- `remind._scan`: `read_meta` → `read_meta_ro` (remind.py:101); `can_complete(...)` →
  `can_complete(..., persist=False)` (remind.py:119).
- `status._meta`: `read_meta` → `read_meta_ro` (status.py:41).
- `gate_policy`: `can_complete(...)` → `can_complete(..., persist=False)` (gate_policy.py:190).
- `ack.run`: unchanged — keeps the `persist=True` default (ack.py:82).

See `impl-plan.md` for the TDD step sequence.
