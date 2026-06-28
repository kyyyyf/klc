# Implementation plan — KLC-054

## step-1 — scaffold state_sync module with pull_rebase and StateConflictError

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

## step-2 — implement commit_and_push_cas with CAS retry and conflict classification

**Goal:** Add `commit_and_push_cas(paths, msg, ticket, klc_dir, remote, max_retries)` with non-fast-forward detection, same-ticket vs other-ticket classification, and retry loop; write the full test suite (AC-2, AC-3, AC-4, AC-5).

**RED:** `tests/test_state_sync.py::TestCommitAndPushCas::test_fast_forward_push` — fails because `commit_and_push_cas` is not yet defined.

**GREEN:** Implement `commit_and_push_cas` — stage, commit, push; on non-fast-forward exit code, run `git fetch`, inspect changed paths in `FETCH_HEAD` vs `HEAD` to classify same-ticket vs other-ticket; rebase and retry or raise `StateConflictError`.

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/test_state_sync.py -x -q`

**Expected:** `5 passed`

**COMMIT:** `KLC-054 step-2: commit_and_push_cas with CAS retry and conflict classification`

**Affected files:** `core/skills/state_sync.py`, `tests/test_state_sync.py`

**Interfaces:**
```python
def commit_and_push_cas(
    paths: list[Path],
    msg: str,
    ticket: str,
    klc_dir: Path,
    remote: str = "origin",
    max_retries: int = 3,
) -> None:
    """Stage paths, commit msg, push to remote with CAS retry.

    Raises:
        ValueError: if any path in paths does not exist.
        ConfigError: if remote is not configured.
        StateConflictError: if remote has commits under tickets/<ticket>/.
        RetryExhaustedError: if max_retries exceeded on other-ticket race.
    """
```

**Depends on:** step-1

**Code sketch:**
```python
def commit_and_push_cas(
    paths: list[Path],
    msg: str,
    ticket: str,
    klc_dir: Path,
    remote: str = "origin",
    max_retries: int = 3,
) -> None:
    for p in paths:
        if not p.exists():
            raise ValueError(f"path does not exist: {p}")
    _git(["git", "add", "--"] + [str(p) for p in paths], cwd=klc_dir)
    _git(["git", "commit", "-m", msg], cwd=klc_dir)

    ticket_prefix = f"tickets/{ticket}/"
    for attempt in range(max_retries + 1):
        result = subprocess.run(
            ["git", "push", remote, "HEAD"],
            cwd=klc_dir, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        if "non-fast-forward" not in result.stderr and "rejected" not in result.stderr:
            raise RuntimeError(result.stderr.strip())
        # Classify: fetch and inspect incoming commits
        subprocess.run(["git", "fetch", remote], cwd=klc_dir, capture_output=True)
        log = subprocess.run(
            ["git", "log", "--name-only", "--format=", "HEAD..FETCH_HEAD"],
            cwd=klc_dir, capture_output=True, text=True,
        ).stdout
        touched = [ln.strip() for ln in log.splitlines() if ln.strip()]
        same_ticket = any(f.startswith(ticket_prefix) for f in touched)
        if same_ticket:
            raise StateConflictError(
                f"remote has commits under {ticket_prefix!r}; single-writer violated"
            )
        if attempt >= max_retries:
            raise RetryExhaustedError(
                f"non-fast-forward persists after {max_retries} retries"
            )
        # Other-ticket race: rebase and retry
        subprocess.run(["git", "rebase", f"{remote}/HEAD"], cwd=klc_dir, capture_output=True)
```
