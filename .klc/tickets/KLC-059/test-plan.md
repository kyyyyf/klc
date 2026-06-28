---
ticket: KLC-059
authority: hybrid
last_generated: 2026-06-27T08:30:00Z
---

# Test plan — KLC-059

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | e2e | tests/integration/test_remind.py::test_remind_silent_when_nothing_to_do | No held completable ticket in env |
| AC-2 | e2e | tests/integration/test_remind.py::test_remind_fires_when_held_and_completable | Fake meta.json with holder=current identity, can_complete=True |
| AC-3 | e2e | tests/integration/test_remind.py::test_remind_silent_for_other_holder | Fake meta.json with holder.id != git user.email |
| AC-4 | e2e | tests/integration/test_remind.py::test_hook_always_exits_zero | Invoke hook script directly; verify exit code 0 even with bad env |
| AC-5 | e2e | tests/integration/test_remind.py::test_statusline_flag_emits_same_line | Invoke `klc remind --statusline`; verify output matches AC-2 format |

## Edge cases
- `KLC_TICKET` env var not set: remind must scan all tickets in `.klc/tickets/` for the current identity, or exit silently if no directory found.
- `phase_completion.can_complete` raises an exception: remind must swallow the error and exit 0 (non-blocking).
- `git config user.email` not set: remind falls back to `$USER` for identity comparison, matching intake.py's `_git_user()` behaviour.
- Ticket in `:ack-needed` or `:ack` state (not `:work`): must be silently skipped even if can_complete returns True.
- Multiple tickets held and completable simultaneously: remind emits one line per completable ticket.

## Regression scenarios
- `gate.py` hook continues to block pick_required:ack-needed independently of remind — adding remind.py to hooks.json must not change gate.py behaviour.
- `klc status` output is unaffected by this change.
- `phase_completion.can_complete` contract is not modified; all existing callers (ack.py, gate_policy.py) are unaffected.

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
