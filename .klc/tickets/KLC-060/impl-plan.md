---
ticket: KLC-060
authority: hybrid
last_generated: 2026-06-27T09:00:00Z
---

# Implementation plan — KLC-060

Surface the current-phase `holder` and a "waiting on ack from `<id>`" hint in
`klc board` and `klc status`, derived read-only from `meta.json` via one shared
helper (`core/skills/holder_display.py`, Option B / D-001).

Track: XS-shaped (3 one-commit steps). TDD-ordered: each step writes its RED
test first, confirms it fails, then makes the smallest change to pass.

Key references (all source-verified 2026-06-27):
- `core/phases/board.py:33-37` projects `{key, track, kind}` per ticket.
- `core/phases/status.py:117,129,139` — `_annotate_current(p, cur_state, meta)`
  with the `state == _ph.STATE_ACK_NEEDED` branch.
- `core/skills/phases.py:37-40` — `STATE_ACK_NEEDED = "ack-needed"`.

---

## step-1 — Add holder_display helper with null-tolerant formatters

**Goal:** Add a pure helper `core/skills/holder_display.py` that formats the
holder id and the waiting-on-ack hint from a `meta` dict, returning `None` for
every degraded shape (no holder, no id, empty id).

**RED:** Write `tests/integration/test_holder_display.py` asserting
`holder_label` and `waiting_hint` over the full shape matrix. Covers test-plan
edge cases: holder present with id, holder key present but `id` missing/null,
empty-string id treated as absent, and `waiting_hint` returning a string only
when `state == "ack-needed"` with an id (negative + fail-closed coverage for
AC-3 / C-002).

**Interfaces:**
- `holder_display.holder_label(meta: dict) -> str | None`
- `holder_display.waiting_hint(meta: dict, state: str) -> str | None`

**Expected:** `pytest` reports the new tests fail before GREEN (ImportError /
assertion), then `10 passed` after GREEN (exact count may differ as rows are
added; all asserted rows pass).

**VERIFY:** `python3 -m pytest tests/integration/test_holder_display.py -q`

**COMMIT:** `KLC-060 step-1: holder_display helper with null-tolerant formatters`

**Affected:**
- `core/skills/holder_display.py` (new)
- `tests/integration/test_holder_display.py` (new)

**Code sketch:**
```python
# core/skills/holder_display.py
from __future__ import annotations

STATE_ACK_NEEDED = "ack-needed"


def _holder_id(meta: dict) -> str | None:
    holder = (meta or {}).get("holder")
    if not isinstance(holder, dict):
        return None
    hid = holder.get("id")
    if not isinstance(hid, str) or not hid.strip():
        return None
    return hid


def holder_label(meta: dict) -> str | None:
    """Holder id for the current phase, or None when absent/degraded."""
    return _holder_id(meta)


def waiting_hint(meta: dict, state: str) -> str | None:
    """`waiting on ack from <id>` only in ack-needed with a holder id."""
    if state != STATE_ACK_NEEDED:
        return None
    hid = _holder_id(meta)
    return f"waiting on ack from {hid}" if hid else None
```

**Depends-on:** none

---

## step-2 — Wire holder into `klc board` (text + --json)

**Goal:** `klc board` surfaces the holder id in the text row and as an omitted-
when-absent `holder_id` key in `--json`, leaving holder-less rows unchanged.

**RED:** Write `tests/integration/test_board_holder.py` with the AC-1 / AC-3
rows from test-plan.md: `test_board_text_shows_holder_id`,
`test_board_json_shows_holder_id`, `test_board_no_holder_unchanged`,
`test_board_no_holder_no_key_error`, `test_board_json_no_holder_valid_json`,
`test_board_does_not_write_meta`. Tests subprocess `scripts/klc board` against a
temp `PROJECT_ROOT` (harness pattern from `test_retrack.py`). The holder-absent
rows are the fail-closed signal and are confirmed failing before GREEN.

**Interfaces:** none (no new public symbol; reuses
`holder_display.holder_label`).

**Expected:** new tests fail before GREEN, then `6 passed`.

**VERIFY:** `python3 -m pytest tests/integration/test_board_holder.py -q`

**COMMIT:** `KLC-060 step-2: surface holder id in klc board text and --json`

**Affected:**
- `core/phases/board.py`
- `tests/integration/test_board_holder.py` (new)

**Code sketch:**
```python
# core/phases/board.py — inside the per-ticket projection (around lines 33-37)
import holder_display  # added alongside the existing `from _paths import ...`

rec = {
    "key":   m.get("ticket"),
    "track": m.get("track"),
    "kind":  m.get("kind"),
}
label = holder_display.holder_label(m)
if label:                       # omit the key entirely when absent (D-002)
    rec["holder_id"] = label
by_phase[m.get("phase", "?")].append(rec)

# text render (around line 51): append holder only when present
held = f"  held by {e['holder_id']}" if e.get("holder_id") else ""
print(f"  {e['key']}  track={e['track'] or '?':<2}  kind={e['kind'] or '?'}{held}")
```

**Depends-on:** step-1

---

## step-3 — Wire holder + waiting hint into `klc status`

**Goal:** `klc status <ticket>` shows the holder id in the current-phase
annotation, and `waiting on ack from <id>` when the phase is `ack-needed`,
leaving holder-less and non-ack-needed renders unchanged.

**RED:** Write `tests/integration/test_status_holder.py` with the AC-2 / AC-3
rows from test-plan.md: `test_status_ack_needed_shows_waiting_hint`,
`test_status_other_state_shows_holder_no_waiting`,
`test_status_no_holder_no_crash`, `test_status_does_not_write_meta`. Subprocess
`scripts/klc status <ticket>` against a temp `PROJECT_ROOT`. The non-ack-needed
and holder-absent rows are the negative / fail-closed signal, confirmed failing
before GREEN.

**Interfaces:** none (reuses `holder_display.holder_label` /
`holder_display.waiting_hint`; `_annotate_current(p, cur_state, meta)` signature
unchanged).

**Expected:** new tests fail before GREEN, then `4 passed`.

**VERIFY:** `python3 -m pytest tests/integration/test_status_holder.py -q`

**COMMIT:** `KLC-060 step-3: surface holder and waiting-on-ack in klc status`

**Affected:**
- `core/phases/status.py`
- `tests/integration/test_status_holder.py` (new)

**Code sketch:**
```python
# core/phases/status.py — inside _annotate_current (around lines 129-146)
import holder_display  # added alongside `import phases as _ph`

def _annotate_current(phase: _ph.Phase, state: str, meta: dict) -> str:
    base = ...  # existing branch logic, unchanged (work / ack-needed / ack)
    wait = holder_display.waiting_hint(meta, state)
    if wait:
        return f"{base} · {wait}"
    label = holder_display.holder_label(meta)
    if label:
        return f"{base} · held by {label}"
    return base
```
Note: the `base` assignment in the sketch stands in for the existing branch
ladder (lines 130-146) which is kept verbatim; the new tail wraps its return
value so `STATE_ACK_NEEDED` still reaches `waiting_hint` and other states fall
through to `holder_label`.

**Depends-on:** step-1

---

## YAGNI / self-review

- 3 steps, linear deps (step-2 and step-3 each depend only on step-1; no
  forward references).
- Every step is behaviour-changing at a public entry point and carries an
  explicit RED test mapped to test-plan rows, a VERIFY command, and an Expected
  output. No wiring-only step, so no `RED: not applicable` is used.
- Each step is one logical commit with a `KLC-060 step-N:` subject.
- One new source file (`holder_display.py`) for a genuinely new component; the
  other two steps edit existing files in place.
- No new external dependency (spec/ADR call for none; ADR_NEEDED=no).
- No abstraction beyond the two helper functions the two surfaces both need.
- API-existence check: the only existing-module symbol referenced in sketches
  is `_ph.STATE_ACK_NEEDED` (verified core/skills/phases.py:38) and the existing
  `_annotate_current` signature (verified status.py:129); all `holder_display.*`
  refs are the new helper from step-1. No unresolved refs.
