---
ticket: KLC-054
authority: hybrid
last_generated: 2026-06-27T08:30:00Z
---

# Test plan — KLC-054

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_state_sync.py::TestPullRebase::test_clean_pull_rebase | local bare repo; remote has no new commits |
| AC-2 | acceptance | tests/test_state_sync.py::TestCommitAndPushCas::test_fast_forward_push | stages one file, commits, pushes to bare remote; asserts return success |
| AC-3 | acceptance | tests/test_state_sync.py::TestCommitAndPushCas::test_other_ticket_rebase_and_retry | remote has commit on different ticket dir; expects transparent retry and success |
| AC-4 | acceptance | tests/test_state_sync.py::TestCommitAndPushCas::test_same_ticket_conflict_raises | remote has commit on same ticket dir; expects StateConflictError raised |
| AC-5 | acceptance | tests/test_state_sync.py (full file) | entire suite uses only local bare repos, zero network access; CI gate: `pytest tests/test_state_sync.py` exits 0 |

## Edge cases

- Max-retries exhausted (other-ticket race loops more than 3 times): `commit_and_push_cas` must raise `RetryExhaustedError` rather than looping forever.
- `pull_rebase()` encounters a rebase conflict (local and remote both modified same file): must raise `RebaseConflictError` and leave the working tree in a recoverable state (rebase aborted).
- `paths` argument contains a file that does not exist: must raise `ValueError` before any git operation.
- Bare repo has no upstream configured: `commit_and_push_cas` must raise `ConfigError` naming the missing remote.

## Regression scenarios

- state_sync imported by lifecycle.py callers: adding the module must not break existing `lifecycle.py` imports or tests (run `pytest tests/test_jira_sync.py` after adding `state_sync.py` to confirm no sys.path pollution).
- Subprocess shell-injection: `msg` argument containing shell metacharacters (`$(...)`, `;`, backticks) must be passed as a list argument to `subprocess.run`, never via `shell=True`.

## Manual checklist

(estimate.manual = 0 — no manual steps required)

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
