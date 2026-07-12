---
ticket: KLC-056
kind: build-log
---

# Build log — KLC-056

Built in an isolated worktree by a build sub-orchestrator, strict TDD
(test-only RED commit then impl GREEN commit per step). Branch
`feature/klc-056-holder`.

## Step 1 — 2026-07-12
**Attempt**: `core/skills/holder.py` — `HolderConflictError` (carries `.holder`)
and `acquire_holder(ticket, identity)`: first-grab when holder absent/null,
idempotent for the same id (preserves `since`), `HolderConflictError` for a
different id (AC-1/2/3/8). `since` is ISO-8601 UTC (`...Z`). Import of
`lifecycle` copied verbatim from `gate_policy.py` (guarded `sys.path.insert`
of `core/skills`, then `import lifecycle`; references go through the module so
tests can monkeypatch `lifecycle.read_meta`/`write_meta`).
**Outcome**: green
**Notes**: RED commit `8e513de` (tests only) failed with
`ModuleNotFoundError: No module named 'holder'`; GREEN commit `9b4cbae`.

## Evidence

```
$ python3 -m pytest tests/test_holder.py -v
9 passed in 0.04s
```

## Step 2 — 2026-07-12
**Attempt**: `release_holder(ticket, identity)` — clears holder when caller
owns it (True), no-op when null (False), `HolderConflictError` for a different
id (AC-4/5/6). AC-7 verified by spying on `builtins.open`, `subprocess.run`,
`subprocess.Popen`: zero calls — holder.py performs no filesystem I/O and no
git ops, delegating all persistence to `lifecycle.read_meta`/`write_meta`.
**Outcome**: green
**Notes**: RED commit `74b5dee` (tests only) failed with
`AttributeError: module 'holder' has no attribute 'release_holder'`; GREEN
commit `6bc287a`.

## Evidence

```
$ python3 -m pytest tests/test_holder.py -v
14 passed in 0.04s
```

## Notes

Spec suggested 8 tests; the build split ACs into 14 finer-grained cases
(absent-vs-null holder, missing-vs-empty identity fields) for stronger
coverage of the same ACs.
