---
ticket: KLC-021
phase: review
authority: agent
verdict: CHANGES REQUESTED
reviewed_at: 2026-06-08
---

# KLC-021 review report

## Summary

CHANGES REQUESTED. The managed-mode implementation compiles and the current
tests pass, but this pass found blocking contract and coverage gaps against
`.klc/tickets/KLC-021/spec.md`.

ISSUES_TOTAL=9 ISSUES_BLOCKING=7

---

## Blocking Issues

### [HIGH] Managed Jira prompt runs outside ack/next decision points - core/skills/lifecycle.py:286

`set_state()` calls `_jira_push_after_state()` for every state write. That
means managed-mode divergence detection can run on `jump`, `abort`, skipped
phase bookkeeping, terminal archiving, and other low-level writes, not only
ack/next. KLC-021 decision D-001 says "Only ack/next prompt", and the goal says
choice happens at the decision point inline.

Fix: gate managed prompting by `source` / caller so only ack and next/advance
paths invoke the managed prompt. Other state writes should either skip managed
sync or record telemetry without prompting, depending on the intended contract.

### [HIGH] Required `jira_sync.push(ticket)` API is missing - core/skills/jira_sync.py:637

AC-3 requires `jira_sync.push(ticket) -> Result`, and the implementation plan
names `push()` as the explicit push API. The implementation added
`push_to_jira(ticket, client, cfg)` instead, with no `push` wrapper or alias in
`jira_sync.py`. Existing tests import `push_to_jira`, so they pass while the
specified public API remains absent.

Fix: add the spec-level `push(ticket)` entry point, loading config/client
internally or providing a backwards-compatible wrapper around `push_to_jira`;
then update tests to import and exercise `jira_sync.push`.

### [HIGH] Managed non-TTY records an unsupported conflict type - core/skills/lifecycle.py:260

AC-7 restricts `meta.json:jira_sync.conflicts[].type` to
`jira-moved-externally | transition-blocked | required-field | issue-missing`.
The non-TTY divergence path writes `"klc-ahead"` when Jira was not externally
moved. That makes doctor-visible conflict metadata inconsistent with the
documented schema and future code that switches on the allowed types.

Fix: either extend the spec/schema/tests to include `klc-ahead`, or map this
case to an allowed conflict type with enough detail to distinguish it.

### [HIGH] `reconcile push` no-op skips required `jira_sync` metadata - core/phases/jira.py:198

AC-6/AC-7 require the explicit push entry point to write the
`meta.json:jira_sync` block. `_reconcile_push` returns success immediately when
Jira is already at the target status, before calling `_update_meta_jira_sync`.
A fresh or stale ticket can therefore run `klc jira reconcile <KEY> push`,
receive success, and still have no updated `last_synced_at`,
`last_jira_status`, `last_klc_phase`, or `last_action`.

Fix: treat the no-op as a successful sync observation and update
`meta.jira_sync` before returning.

### [HIGH] Tests cover `push_to_jira`, not the required `jira_sync.push` API - tests/integration/test_jira_managed.py:153

The AC-3 tests import and call `push_to_jira`; they never assert that
`jira_sync.push(ticket)` exists or works. This is why the public API mismatch
above was not caught.

Fix: update the AC-3 tests to exercise `jira_sync.push(ticket)` directly,
including success, no-op, transition-blocked, and unreachable Jira results.

### [HIGH] TTY prompt branches from AC-4 are not automated - tests/integration/test_jira_managed.py:219

The test file covers mirror mode and managed non-TTY paths, but not the TTY
choices required by AC-4: klc-moved pick 1/2 and PM-conflict pick 1/2/3. The
ticket's own test plan lists these as cases 4.3 through 4.7, but they are not
implemented in the integration test file.

Fix: add mocked `sys.stdin.isatty`, `sys.stdout.isatty`, and input tests for
all five prompt choices, asserting transition/comment calls and conflict
metadata.

### [HIGH] `klc jira sync` and `reconcile push` CLI paths lack integration coverage - tests/integration/test_jira_managed.py:338

AC-5 and AC-6 are CLI-facing contracts. The managed integration test main list
runs build-plan, library push, lifecycle non-TTY, managed-ticket filtering, and
doctor conflict checks, but there are no calls to `cmd_sync`, `cmd_reconcile`,
`klc jira sync`, or `klc jira reconcile`. As a result, CLI drift such as the
metadata no-op bug is not covered.

Fix: add fake-client CLI tests for `sync --dry-run`, `sync --apply`,
`reconcile push` success, no-op metadata update, and transition-blocked exit 1.

---

## Non-Blocking Issues

### [MEDIUM] CLI reconcile duplicates the push implementation - core/phases/jira.py:174

`core/phases/jira.py` reimplements transition lookup, provenance comment,
conflict write, and metadata update instead of delegating to the new `jira_sync`
push API. This already produced behavioral drift: the library returns
structured `{ok, action, detail}` and records `transition-blocked`, while the
CLI has a separate no-op path and separate metadata helper.

Fix: make `klc jira reconcile <KEY> push` call the single `jira_sync.push`
implementation and translate its result to CLI output/exit code.

### [LOW] `SyncPlan` API is appended after the `__main__` block - core/skills/jira_sync.py:527

The module imports correctly because the `if __name__ == "__main__"` block does
not run on import, but library API definitions after the CLI entry point are
easy to miss and contributed to the public API mismatch above.

Fix: move `SyncPlan`, `build_plan`, and push helpers above the CLI block.

---

## Reviewer Partials

### Security

No KLC-021-specific security issues found in managed-mode prompt/push code.
The TTY prompt reads from stdin only after TTY detection; non-TTY paths do not
call `input()`.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

### Architecture

ISSUES_TOTAL=5 ISSUES_BLOCKING=4

### Performance

No performance issues found. Mirror mode still dispatches to legacy
`jira_sync.push_phase`, and managed mode only performs Jira reads/prompts when
`mode: managed` applies to the ticket.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

### Test Coverage

ISSUES_TOTAL=3 ISSUES_BLOCKING=3

---

## Verification Run

These checks were run during review and passed:

- `python3 tests/integration/test_jira_managed.py`
- `python3 tests/integration/test_jira_core.py`
- `python3 tests/e2e_pipeline.py`
- `python3 core/phases/doctor.py`
- `python3 -m py_compile core/skills/jira_sync.py core/skills/lifecycle.py core/skills/jira_config.py core/phases/jira.py core/phases/doctor.py core/skills/validate_config.py`

## Verdict

**CHANGES REQUESTED** - blocking findings remain. For ack, use request-changes:
`klc ack KLC-021 --pick 2`.
