---
ticket: KLC-062
phase: design
authority: human
last_generated: 2026-07-16
picked_option: A
---

# Implementation plan — KLC-062

Make `klc remind` (and `klc status`) truly read-only by making the two write
sites side-effect-optional behind backward-compatible defaulted keywords. Tests
are written first (RED) at the public verb entry point and confirmed failing
before the GREEN code. Foundational helpers (`read_meta_ro`, the `persist`
keyword) are built and proven before the verbs are re-wired, and the AC-3
regression guard is added last so it demonstrably still passes under the new
default.

All integration tests fabricate a temp `PROJECT_ROOT` with hand-written
`meta.json` / `spec.md`; no network and no real git remote (mirrors the existing
`tests/integration/test_remind.py` harness).

## step-1 [x] — non-persisting meta read: read_meta_ro + status wiring

**Goal:** Add `lifecycle.read_meta(ticket, *, persist_migration: bool = True)` and
a thin `lifecycle.read_meta_ro(ticket)` wrapper, then switch `status._meta` to the
read-only variant. The legacy migration still runs in-memory (display stays
correct) but is no longer written back to disk on a read (AC-2). Closes the
`status` read-only contract violation.

**RED:** `tests/integration/test_status_holder.py::test_status_does_not_write_meta_legacy_phase`
— fabricate a ticket with a legacy `meta.json:phase` (e.g. `design-pending`),
snapshot `meta.json` bytes, run `klc status`; asserts exit 0, the migrated phase
shows in output, and `meta.json` is byte-identical. Fails today because
`read_meta` write-backs the migration.

**GREEN:** Thread `persist_migration` into `read_meta`: only call `write_meta`
when `_migrate_legacy_phase(meta)` AND `persist_migration`. Add
`read_meta_ro(ticket)` → `read_meta(ticket, persist_migration=False)`. Point
`status._meta` at `read_meta_ro`.

**Interfaces:**
```python
def read_meta(ticket: str, *, persist_migration: bool = True) -> dict: ...
def read_meta_ro(ticket: str) -> dict: ...
```

**Expected:** `1 passed` for the new test; existing `test_status_holder.py` and
`test_board_holder.py` stay green.

**VERIFY:** `cd "$PROJECT_ROOT" && python -m pytest tests/integration/test_status_holder.py -x -q`

**COMMIT:** `KLC-062 step-1: read_meta_ro suppresses legacy-migration write-back; status uses it`

**Affected:** `core/skills/lifecycle.py`, `core/phases/status.py`,
`tests/integration/test_status_holder.py`.

**Code sketch:**
```python
# lifecycle.py
def read_meta(ticket, *, persist_migration=True):
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        raise FileNotFoundError(...)
    meta = json.loads(p.read_text(encoding="utf-8"))
    if _migrate_legacy_phase(meta) and persist_migration:
        write_meta(ticket, meta)
    return meta

def read_meta_ro(ticket):
    return read_meta(ticket, persist_migration=False)
```

**Depends-on:** none

## step-2 [x] — side-effect-optional completion probe; remind wired read-only

**Goal:** Add keyword-only `persist: bool = True` to `can_complete`,
`can_complete_discovery`, and `can_complete_discovery_lite`, guarding both write
sites (`_sync_risk_tags(ticket)` and the floor-guard `_lc.write_meta` audit)
so they fire only when `persist` is True. Re-wire `remind._scan` to
`read_meta_ro` plus the `persist=False` completion probe, and switch the
`gate_policy` advisory probe to `persist=False`. The completability *decision*
(including the downgrade-safety block) is unchanged. Closes AC-1.

**RED:** `tests/integration/test_remind.py::test_remind_does_not_write_meta_for_completable_discovery`
— fabricate a `discovery:work` ticket held by the caller with a fully valid
`spec.md` + `meta.json` (passes every discovery gate; `risk_tags` in frontmatter),
snapshot `meta.json` bytes, run `klc remind`; asserts the reminder line prints,
exit 0, and `meta.json` byte-identical. Fails today because `_sync_risk_tags`
rewrites `meta.json`. Companion RED:
`::test_remind_does_not_write_meta_legacy_phase` (held completable legacy
`<phase>:work` ticket → byte-identical).

**GREEN:** Add `persist` param and gate `if persist: _sync_risk_tags(ticket)` at
both success paths and `if persist:` around the floor-guard audit write. Thread
`persist` from `can_complete` into the two discovery helpers. In `remind._scan`
call `read_meta_ro` and `can_complete(ticket, phase_id, persist=False)`; in
`gate_policy` call `can_complete(ticket, phase_id, persist=False)`.

**Interfaces:**
```python
def can_complete(ticket, phase_id, *, persist=True) -> tuple[bool, str]: ...
def can_complete_discovery(ticket, *, persist=True) -> tuple[bool, str]: ...
def can_complete_discovery_lite(ticket, *, persist=True) -> tuple[bool, str]: ...
```

**Expected:** `2 passed` for the new tests; the whole existing
`test_remind.py` suite stays green.

**VERIFY:** `cd "$PROJECT_ROOT" && python -m pytest tests/integration/test_remind.py -x -q`

**COMMIT:** `KLC-062 step-2: persist=False completion probe; remind is read-only`

**Affected:** `core/skills/phase_completion.py`, `core/phases/remind.py`,
`core/skills/gate_policy.py`, `tests/integration/test_remind.py`.

**Code sketch:**
```python
# phase_completion.py
def can_complete(ticket, phase_id, *, persist=True):
    if phase_id == "discovery":
        return can_complete_discovery(ticket, persist=persist)
    if phase_id == "discovery-lite":
        return can_complete_discovery_lite(ticket, persist=persist)
    ...
# in can_complete_discovery success path:
    if persist:
        _sync_risk_tags(ticket)
# floor-guard audit:
    if persist:
        meta["track_source"] = "discovery"
        meta["blast_radius"] = {...}
        _lc.write_meta(ticket, meta)
# remind.py
    meta = _lc.read_meta_ro(ticket)
    ok, _msg = _pc.can_complete(ticket, phase_id, persist=False)
```

**Depends-on:** step-1

## step-3 [x] — AC-3 regression guard: ack still persists risk_tags

**Goal:** Add a regression test proving the default (`persist=True`) path still
writes `risk_tags` at the real completion transition, so Option A cannot silently
drop the functional behaviour AC-3 protects.

**RED: not applicable** — this is a characterization/regression guard. With the
`persist=True` default preserved in step-2, `klc ack` on a completable discovery
ticket already persists `risk_tags`; the test asserts existing behaviour and
passes without further production code. (Marked not applicable per the KLC-039
red-before-green gate for non-behaviour-adding steps.)

**GREEN:** No production change. Add
`tests/integration/test_ack_risk_tags.py::test_ack_discovery_persists_risk_tags`:
fabricate a completable `discovery:work` ticket held by the caller whose `spec.md`
frontmatter has `risk_tags: [data]`; run `klc ack <KEY> --pick 1` (or the
manual-completion detection at `ack.py:82`); assert `meta.json:risk_tags == ["data"]`
afterward.

**Interfaces:** none (test-only).

**Expected:** `1 passed`.

**VERIFY:** `cd "$PROJECT_ROOT" && python -m pytest tests/integration/test_ack_risk_tags.py -x -q`

**COMMIT:** `KLC-062 step-3: regression guard — ack persists risk_tags (AC-3)`

**Affected:** `tests/integration/test_ack_risk_tags.py` (new).

**Code sketch:**
```python
# test asserts the ack/completion path still persists risk_tags
meta = json.loads((tdir / "meta.json").read_text())
assert meta["risk_tags"] == ["data"]
```

**Depends-on:** step-2
