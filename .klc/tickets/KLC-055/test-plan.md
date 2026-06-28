---
ticket: KLC-055
authority: hybrid
last_generated: 2026-06-27T08:00:00Z
---

# Test plan — KLC-055

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_identity.py::test_current_returns_email | monkeypatch git subprocess; assert email returned |
| AC-1 | acceptance | tests/test_identity.py::test_current_falls_back_to_name | email unset, name set; assert name returned |
| AC-1 | acceptance | tests/test_identity.py::test_current_falls_back_to_USER_env | both git keys unset, USER env set; assert env var returned |
| AC-2 | acceptance | tests/test_identity.py::test_current_exits_when_nothing_set | all sources unset; assert SystemExit with non-empty message |
| AC-2 | acceptance | tests/test_identity.py::test_exit_message_mentions_git_config | SystemExit message contains `git config --global user.email` |

## Edge cases
- `git` binary not on PATH (OSError): treated as unset, fall through to next source
- `git config` subprocess times out: treated as unset, fall through to next source
- `user.email` set to whitespace-only string: treated as unset (strip + empty-check)
- `$USER` set to empty string: treated as unset → SystemExit

## Regression scenarios
- `core/phases/intake.py` still produces a non-empty owner field after the refactor (i.e., `_git_user()` delegation to `identity.current()` does not break the intake flow)

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
