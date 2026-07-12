---
ticket: KLC-053
kind: build-log
---

# Build log — KLC-053

Built in an isolated worktree by a build sub-orchestrator, strict TDD
(test-only RED commit then impl GREEN commit per step). Branch
`feature/klc-053-state-init`. `klc state init` was exercised only inside
throwaway temp git repos — never against the real repo.

## Step 1 — 2026-07-12
**Attempt**: new `core/phases/state.py` with `run(argv)` implementing
`state init [<remote>]`; creates the `klc-state` orphan branch as a git
worktree at `.klc/` when no such branch exists, idempotent on a second run
(AC-2). git 2.43 supports `git worktree add --orphan -b klc-state .klc`
directly; an initial `--allow-empty` root commit gives the unborn branch a ref
while keeping history disjoint from `main`.
**Outcome**: green
**Notes**: RED commit `6e1e306` (tests only) → 3 failed
(`FileNotFoundError: .../core/phases/state.py`); GREEN commit `610ff19`.

## Evidence

```
$ python3 -m pytest tests/integration/test_state_init.py -q
5 passed in 0.50s
```

## Step 2 — 2026-07-12
**Attempt**: when `origin` already has `klc-state`, `state init` adds the
worktree tracking `origin/klc-state` and preserves existing `.klc/tickets`
content (moved aside to `.klc.init-bak`, restored after `git worktree add`,
local files winning on collision) (AC-1). Wired `"state"` into the dispatcher's
`OPERATIONAL_CMDS` in `scripts/klc` so `klc state init` routes to
`core/phases/state.py:run(["init"])`.
**Outcome**: green
**Notes**: RED commit `46bb917` (tests only) → 2 failed
(`test_state_init_tracks_origin_and_preserves_local`, and dispatch test with
`klc: unknown subcommand: state`); GREEN commit `493f0ab`. Branch-source order:
local `klc-state` → remote `origin` → orphan.

## Evidence

```
$ python3 -m pytest tests/integration/test_state_init.py -q
5 passed in 0.50s
$ python3 -m pytest tests/ -k state_init -q --ignore=tests/fixtures
5 passed, 520 deselected in 0.63s
```

## Notes

`tests/fixtures/tiny-py/tests/` excluded via `--ignore=tests/fixtures` —
pre-existing unrelated fixture with its own `src` import.
