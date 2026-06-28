# Agent prompt — KLC-054 · build:work · step-1

Ticket: **KLC-054** · track: **S** · kind: **unknown**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Add a `state_sync` module with `pull_rebase()` and `commit_and_push_cas(paths, msg)` that provides git CAS (non-fast-forward rejection) coordination for the multi-user `.klc/` state repo, distinguishing a same-ticket conflict (single-writer violation, surface to caller) from an other-ticket rebase (absorb and retry).

## Acceptance Criteria

- [ ] AC-1: `pull_rebase()` runs `git pull --rebase` on the `.klc/` directory and returns without error when the rebase succeeds cleanly (no diverged local commits).
- [ ] AC-2: `commit_and_push_cas(paths, msg)` stages the given paths, creates a commit with the given message, pushes to the configured remote, and returns successfully on a fast-forward push.
- [ ] AC-3: When `git push` is rejected with a non-fast-forward error and the remote has commits only touching files outside `tickets/<current-ticket>/`, `commit_and_push_cas` transparently rebases and retries the push (up to a configurable max-retries limit, default 3).
- [ ] AC-4: When `git push` is rejected with a non-fast-forward error and the remote has commits touching files inside `tickets/<current-ticket>/`, `commit_and_push_cas` raises `StateConflictError` (same-ticket conflict — single-writer violation) without retrying.
- [ ] AC-5: All four behaviours above are exercised by pytest tests that run entirely against a local bare repo (no network); tests pass under `pytest tests/test_state_sync.py`.

### Current step — step-1

**scaffold state_sync module with pull_rebase and StateConflictError**

**Goal:** Create `core/skills/state_sync.py` with `pull_rebase()`, `StateConflictError`, and `RetryExhaustedError`; add a failing test for `pull_rebase()` that uses a local bare repo.

**RED:** `tests/test_state_sync.py::TestPullRebase::test_clean_pull_rebase` — fails because `state_sync.py` does not exist.

**GREEN:** Create `core/skills/state_sync.py` with `pull_rebase(klc_dir)` that calls `git pull --rebase` via `subprocess.run`; raise `RebaseConflictError` on non-zero exit.

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/test_state_sync.py::TestPullRebase -x -q`

**Expected:** `1 passed`

**COMMIT:** `KLC-054 step-1: scaffold state_sync with pull_rebase and error types`

**Affected files:** `core/skills/state_sync.py`, `tests/test_state_sync.py`

**Interfaces:**
```python
class StateConflictError(Exception): ...   # same-ticket CAS violation
class RebaseConflictError(Exception): ...  # merge conflict during rebase
class RetryExhaustedError(Exception): ...  # max retries hit on other-ticket race
class ConfigError(Exception): ...          # missing remote config

def pull_rebase(klc_dir: Path) -> None:
    """Run `git pull --rebase` in klc_dir. Raises RebaseConflictError on conflict."""
```

**Depends on:** none

**Code sketch:**
```python
import subprocess
from pathlib import Path

class StateConflictError(Exception): ...
class RebaseConflictError(Exception): ...
class RetryExhaustedError(Exception): ...
class ConfigError(Exception): ...

def pull_rebase(klc_dir: Path) -> None:
    result = subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=klc_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        subprocess.run(["git", "rebase", "--abort"], cwd=klc_dir, capture_output=True)
        raise RebaseConflictError(result.stderr.strip())
```

**Affected files**:


**Expected tests**:



### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.

### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/home/ek/projects/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-054 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-054/impl-plan.md`
- Full spec: `.klc/tickets/KLC-054/spec.md`
- Full test-plan: `.klc/tickets/KLC-054/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-054 step-1` and
run `klc step KLC-054 2` to get the next step's card,
or `klc ack KLC-054 --pick 1` if this was the last step.
