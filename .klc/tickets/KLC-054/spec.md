---
ticket: KLC-054
kind: tech
authority: agent
track: S
risk_tags: [data]
---

## Goals

Add a `state_sync` module with `pull_rebase()` and `commit_and_push_cas(paths, msg)` that provides git CAS (non-fast-forward rejection) coordination for the multi-user `.klc/` state — which is a **git worktree of the project's `klc-state` orphan branch** (see KLC-053), pushed to `origin klc-state`. Distinguishes a same-ticket conflict (single-writer violation, surface to caller) from an other-ticket rebase (absorb and retry). The CAS mechanics are independent of where state lives — it operates on whatever git working tree `.klc/` is.

## Acceptance Criteria

- [ ] AC-1: `pull_rebase()` runs `git pull --rebase` on the `.klc/` directory and returns without error when the rebase succeeds cleanly (no diverged local commits).
- [ ] AC-2: `commit_and_push_cas(paths, msg)` stages the given paths, creates a commit with the given message, pushes the `klc-state` branch to `origin` (the worktree's upstream), and returns successfully on a fast-forward push.
- [ ] AC-3: When `git push` is rejected with a non-fast-forward error and the remote has commits only touching files outside `tickets/<current-ticket>/`, `commit_and_push_cas` transparently rebases and retries the push (up to a configurable max-retries limit, default 3).
- [ ] AC-4: When `git push` is rejected with a non-fast-forward error and the remote has commits touching files inside `tickets/<current-ticket>/`, `commit_and_push_cas` raises `StateConflictError` (same-ticket conflict — single-writer violation) without retrying.
- [ ] AC-5: All four behaviours above are exercised by pytest tests that run entirely against a local bare repo (no network); tests pass under `pytest tests/test_state_sync.py`.

## Affected

[!ASSUMPTION if-false=scope-may-expand] state_sync: `core/skills/state_sync.py` — new file, does not exist yet; path is derived from the convention for all other skill modules in `core/skills/`
[!ASSUMPTION if-false=scope-may-expand] tests: `tests/test_state_sync.py` — new file; follows the pattern of `tests/test_jira_sync.py` (src=/home/ek/projects/klc/tests/test_jira_sync.py:1)

## Estimate

complexity: 2
uncertainty: 1
risk: 1
manual: 0
total: 4

DISCOVERY_LITE_DONE
