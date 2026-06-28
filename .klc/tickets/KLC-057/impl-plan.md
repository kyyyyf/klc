---
ticket: KLC-057
phase: design
authority: human
last_generated: 2026-06-28
picked_option: B
adr: design/adr.md
---

# Implementation plan — KLC-057

Wire `state_sync` / `identity` / `holder` into `intake` / `ack` / `next` via a
shared `state_tx` transaction wrapper. Riskiest work first: feature detector and
the wrapper (with its rollback path) are built and unit-tested before any verb is
touched, so the verb steps only compose an already-proven envelope. Every
behaviour step has a RED test at the public entry point.

Tests are written first (RED) and confirmed failing before the GREEN code.
Integration tests use a local bare-repo / stubbed `state_sync` fixture — no
network (AC-10).

Depends on KLC-054/055/056 landing first (A-001). If a sibling deviates from the
pinned contract in `design/adr.md`, this build is blocked at the deviating step.

## step-1 — feature detector: state_feature.enabled()

**Goal:** Add `core/skills/state_feature.py` whose `enabled()` returns True iff
`.klc/` is a git **worktree bound to the `klc-state` branch** (the orphan branch
materialized by KLC-053 `klc state init`), so every other step has one
authoritative no-op switch (D-004 / C-004 / AC-8). There is no remote named
`klc-state`; detection is the worktree's checked-out branch, not a remote.

**RED:** `tests/test_state_feature.py::test_enabled_false_when_klc_is_plain_dir`
— fails because `state_feature` does not exist; asserts `enabled()` is False when
`.klc/` is a plain directory (HEAD is not the `klc-state` branch).

**GREEN:** Implement `enabled()` running `git symbolic-ref --short HEAD` in
`klc_dir()` and checking the result equals `klc-state`; return False on any git
error (fail-safe off).

**Interfaces:**
```python
def enabled() -> bool: ...
```

**Expected:** `2 passed` (plain dir → False; `.klc/` checked out on the `klc-state`
branch → True).

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/test_state_feature.py -x -q`

**COMMIT:** `KLC-057 step-1: state_feature.enabled() detects klc-state worktree`

**Affected:** `core/skills/state_feature.py` (new), `tests/test_state_feature.py` (new).

**Code sketch:**
```python
import subprocess
from _paths import klc_dir

def enabled() -> bool:
    try:
        r = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"],
                           cwd=klc_dir(), capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "klc-state"
```

**Depends-on:** none

## step-2 — state_tx wrapper: no-op path when feature off

**Goal:** Add `core/skills/state_tx.py` context manager that, when
`state_feature.enabled()` is False, performs no pull/push and yields a trivial
handle — guaranteeing the AC-8 byte-for-byte no-op before any sync logic exists.

**RED:** `tests/test_state_tx.py::test_noop_when_feature_off` — fails because
`state_tx` does not exist; with `state_feature.enabled` stubbed False, asserts the
context manager runs the body and calls neither `pull_rebase` nor
`commit_and_push_cas`.

**GREEN:** Implement `state_tx` as a `@contextmanager`: if not
`state_feature.enabled()`, `yield` immediately and return (no git calls).

**Interfaces:**
```python
@contextmanager
def state_tx(ticket: str, paths: list, msg: str): ...
```

**Expected:** `1 passed`

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/test_state_tx.py::test_noop_when_feature_off -x -q`

**COMMIT:** `KLC-057 step-2: state_tx no-op path when feature off`

**Affected:** `core/skills/state_tx.py` (new), `tests/test_state_tx.py` (new).

**Code sketch:**
```python
from contextlib import contextmanager
import state_feature

@contextmanager
def state_tx(ticket, paths, msg):
    if not state_feature.enabled():
        yield None
        return
    # feature-on path added in step-3
    raise NotImplementedError
```

**Depends-on:** step-1

## step-3 — state_tx wrapper: pull on enter, CAS push on exit, rollback on conflict

**Goal:** Complete `state_tx` feature-on path: `pull_rebase` on enter, snapshot
the touched paths, `commit_and_push_cas` on clean exit, and on `StateConflictError`
restore the snapshot (delete created files, restore modified ones) before
re-raising — the single rollback implementation (D-002 / D-005).

**RED:** `tests/test_state_tx.py::test_cas_conflict_rolls_back_local_state` — with
`state_sync` stubbed so `commit_and_push_cas` raises `StateConflictError`, the body
creates a file under the ticket dir; after the context exits the file is gone and
`StateConflictError` propagated. Uses a local bare-repo fixture (no network).

**GREEN:** In the feature-on branch: call `pull_rebase()`; snapshot each
path's prior bytes (or absence); `yield` a handle; on clean exit call
`commit_and_push_cas(paths, msg)` (which pushes the `klc-state` branch to
`origin`); wrap that in `try/except StateConflictError` → restore snapshot, then
re-raise.

**Interfaces:**
```python
def _snapshot(paths): ...      # path -> bytes|None
def _restore(snapshot): ...    # delete-if-None else rewrite
```

**Expected:** `3 passed` (no-op; happy push; conflict-rollback).

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/test_state_tx.py -x -q`

**COMMIT:** `KLC-057 step-3: state_tx pull/push envelope with CAS-conflict rollback`

**Affected:** `core/skills/state_tx.py`, `tests/test_state_tx.py`.

**Code sketch:**
```python
import state_sync, state_feature

@contextmanager
def state_tx(ticket, paths, msg):
    if not state_feature.enabled():
        yield None
        return
    state_sync.pull_rebase()
    snap = _snapshot(paths)
    try:
        yield None
        state_sync.commit_and_push_cas(paths, msg)
    except state_sync.StateConflictError:
        _restore(snap)
        raise
```

**Depends-on:** step-2

## step-4 — intake: uniqueness via CAS + acquire holder, index-append deferred

**Goal:** Wrap intake's create body in `state_tx` so the CAS push enforces key
uniqueness (taken key → rollback, no artifacts, AC-2), the new ticket's first
phase records the current holder (AC-3), and the global-index append moves to
**after** a successful push (D-005); feature-off intake is unchanged (AC-8a).

**RED:** `tests/integration/test_klc057_sync_holder.py::test_intake_taken_key_rejected_no_artifacts`
— with `state_sync` stubbed to reject the push as `StateConflictError`, `intake.run`
exits non-zero with a message naming the key as already taken, and no `meta.json`,
no `raw.md`, no ticket dir, and no global-index entry for the key remain.

**GREEN:** In `intake.run`, after writing meta/raw, enter
`state_tx(ticket, [meta_path, raw_path], msg)`; inside it call
`holder.acquire_holder(ticket, {"id": identity.current(), "machine": hostname})`;
append to the global index only after the `with` block exits cleanly; on
`StateConflictError` print "already taken", remove the ticket dir, return non-zero.

**Interfaces:**
```python
# core/phases/intake.py run(): index-append relocated to post-state_tx
```

**Expected:** `1 passed`

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/integration/test_klc057_sync_holder.py::test_intake_taken_key_rejected_no_artifacts -x -q`

**COMMIT:** `KLC-057 step-4: intake CAS uniqueness + holder acquire, deferred index-append`

**Affected:** `core/phases/intake.py`, `tests/integration/test_klc057_sync_holder.py` (new).

**Code sketch:**
```python
import state_tx, holder, identity, socket, state_sync
ident = {"id": identity.current(), "machine": socket.gethostname()}
try:
    with state_tx.state_tx(args.ticket, [meta_path, raw_path], f"intake {args.ticket}"):
        holder.acquire_holder(args.ticket, ident)
    _append_global_index(args.ticket, meta)   # only after a clean push
except state_sync.StateConflictError:
    shutil.rmtree(tdir, ignore_errors=True)
    sys.stderr.write(f"klc intake: key {args.ticket} already taken\n")
    return 1
```

**Depends-on:** step-3

## step-5 — intake happy path + acquires-holder + feature-off parity

**Goal:** Confirm the happy path: feature-on intake of a free key pushes
successfully, prints `INTAKE_OK`, exit 0 (AC-1), records the holder in the same
push (AC-3); and feature-off intake is byte-for-byte identical to today (AC-8a).

**RED:** `tests/integration/test_klc057_sync_holder.py::test_intake_acquires_holder_in_same_cas_push`
— feature-on, key free, `state_sync` stub accepts the push; after `intake.run`,
`meta.holder.id == identity.current()` and the push payload included both meta and
the holder field; plus `test_intake_happy_path_cas_push_succeeds` asserts
`INTAKE_OK` + exit 0, and `test_feature_off_intake_behavior_identical` asserts no
holder field and identical output with the feature off.

**GREEN:** No new production code expected beyond step-4 if correct; if a test
fails, fix the minimal gap (e.g. holder written before push, output unchanged on
the no-op path).

**Interfaces:** none

**Expected:** `3 passed`

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/integration/test_klc057_sync_holder.py -k intake -x -q`

**COMMIT:** `KLC-057 step-5: intake happy-path, holder-in-push, and feature-off parity tests`

**Affected:** `tests/integration/test_klc057_sync_holder.py`, `core/phases/intake.py` (only if a gap surfaces).

**Code sketch:**
```python
# test asserts holder + uniqueness ride one CAS push; feature-off is a no-op
meta = lifecycle.read_meta("KLC-T1")
assert meta["holder"]["id"] == "alice@example.com"   # AC-3
# feature-off: meta has no "holder" key and stdout == pre-KLC-057 baseline (AC-8a)
```

**Depends-on:** step-4

## step-6 — ack: release holder after advance, before push (ordering + atomicity)

**Goal:** Wrap ack's advance in `state_tx` so a successful forward `ack` runs
pull → existing gate-policy/validation → `apply_ack` advance → `release_holder` →
one CAS push (AC-4/AC-5); a rejected push does not advance the remote phase; the
new wrapping reuses, not replaces, the gate-policy already at ack.py:170-191 (C-005).

**RED:** `tests/integration/test_klc057_sync_holder.py::test_ack_releases_holder_on_forward_transition`
and `::test_ack_cas_rejected_does_not_advance_remote_phase` — first: user holds P,
`ack` advances and `meta.holder` is cleared in the pushed state; second:
`state_sync` stub rejects the push, `ack` exits non-zero with a concurrent-update
message and the remote phase is unchanged.

**GREEN:** In `ack.run`, after the existing `apply_ack` advance, enter
`state_tx(ticket, [meta_path], msg)` and call `holder.release_holder(ticket, ident)`
inside it so release happens after advance and before the push; map
`StateConflictError` to a "concurrent update — retry" non-zero exit.

**Interfaces:**
```python
# core/phases/ack.py run(): release_holder inside state_tx, after apply_ack
```

**Expected:** `2 passed`

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/integration/test_klc057_sync_holder.py -k ack -x -q`

**COMMIT:** `KLC-057 step-6: ack releases holder after advance, before CAS push`

**Affected:** `core/phases/ack.py`, `tests/integration/test_klc057_sync_holder.py`.

**Code sketch:**
```python
new_state = _lc.apply_ack(args.ticket, pick_id)          # existing advance
try:
    with state_tx.state_tx(args.ticket, [meta_path], f"ack {args.ticket}"):
        holder.release_holder(args.ticket, ident)        # after advance, before push
except state_sync.StateConflictError:
    sys.stderr.write("klc ack: concurrent update — retry\n")
    return 1
```

**Depends-on:** step-3

## step-7 — next: first-grab free phase, refuse to steal held phase

**Goal:** Wrap next's advance in `state_tx` so entering a free phase first-grabs it
(current user becomes holder, CAS-pushed, AC-6a) and a phase already held by
another is reported as taken without stealing (AC-6b); feature-off next writes no
holder (AC-8b).

**RED:** `tests/integration/test_klc057_sync_holder.py::test_next_first_grabs_free_phase`
and `::test_next_refuses_to_steal_held_phase` — first: ticket at P:ack with P+1
free; `next` advances to P+1:work and `meta.holder.id` is the current user;
second: P+1 held by another → `acquire_holder` raises `HolderConflictError`, `next`
exits non-zero with a "held by" message and the holder is unchanged.

**GREEN:** In `next.run`, after `advance_to_next`, enter
`state_tx(ticket, [meta_path], msg)` and call `holder.acquire_holder(ticket, ident)`
for the entered phase; map `HolderConflictError` to a "held by <id>" non-zero exit
(no steal — KLC-058 owns stealing).

**Interfaces:**
```python
# core/phases/next.py run(): acquire_holder inside state_tx, after advance_to_next
```

**Expected:** `2 passed`

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/integration/test_klc057_sync_holder.py -k next -x -q`

**COMMIT:** `KLC-057 step-7: next first-grabs free phase, refuses to steal held phase`

**Affected:** `core/phases/next.py`, `tests/integration/test_klc057_sync_holder.py`.

**Code sketch:**
```python
new_state = _lc.advance_to_next(args.ticket, note="klc next")   # existing
try:
    with state_tx.state_tx(args.ticket, [meta_path], f"next {args.ticket}"):
        holder.acquire_holder(args.ticket, ident)
except holder.HolderConflictError as e:
    sys.stderr.write(f"klc next: phase held by {e.holder_id}\n")
    return 1
```

**Depends-on:** step-3

## step-8 — output hygiene + regression sweep

**Goal:** Confirm no git-internals leak on success paths (AC-7), feature-off
ack/next write no holder fields (AC-8b), sync runs inside the per-ticket lock
(AC-9), and the KLC-045 gate-policy + existing verb suites still pass.

**RED:** `tests/integration/test_klc057_sync_holder.py::test_success_path_output_contains_no_git_internals`
asserts intake/ack/next success stdout contains none of: `state-branch`,
`worktree`, `push`, `pull_rebase`, `commit_and_push`, `klc-state`; plus
`::test_feature_off_ack_next_no_holder_fields` and
`::test_sync_runs_inside_per_ticket_lock`.

**GREEN:** Move any leaked diagnostics to stderr/failure paths only; ensure the
`state_tx` call sites sit inside the existing `with acquire_lock(ticket):` blocks.
Minimal edits to the three verbs as failures dictate.

**Interfaces:** none

**Expected:** `3 passed` (this file) and green KLC-045 regression suite.

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/integration/test_klc057_sync_holder.py tests/integration/test_gate_policy.py -x -q`

**COMMIT:** `KLC-057 step-8: output hygiene, feature-off holder, lock-scope and regression tests`

**Affected:** `tests/integration/test_klc057_sync_holder.py`, `core/phases/intake.py`, `core/phases/ack.py`, `core/phases/next.py` (only if a leak/scope gap surfaces).

**Code sketch:**
```python
for line in stdout.splitlines():               # AC-7 success-path hygiene
    assert "klc-state" not in line and "pull_rebase" not in line
# state_tx is entered inside the existing `with acquire_lock(ticket):` block (AC-9)
```

**Depends-on:** step-5, step-6, step-7
