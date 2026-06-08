---
ticket: KLC-021
phase: review
authority: agent
verdict: APPROVED
---

# KLC-021 review report — rework pass

## Summary

APPROVED. All blocking findings from the previous review pass are resolved.
One LOW finding remains (private helper call across modules); non-blocking.

ISSUES_TOTAL=1 ISSUES_BLOCKING=0

---

## Security

No new issues. HTTPS validation added in jira_config.py (KLC-020 HIGH-1 fix).
`_CommentReadError` is a private exception class, not exposed. No shell
injection, no new network paths.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

---

## Architecture

All HIGH architecture findings from previous review resolved:
- Managed hook restricted to `_MANAGED_SOURCES = {"ack","advance","set_state"}`
- `jira_sync.push(ticket)` public wrapper added
- `_reconcile_push` delegates to `jira_sync.push()` — no duplicate logic
- issue-missing/unreachable recorded in meta before returning error
- Successful push/sync clears stale conflicts via `clear_conflicts=True`

### [LOW] `cmd_sync --apply` calls private `_js._update_jira_sync_meta`

`jira.py:cmd_sync` does `import jira_sync as _js; _js._update_jira_sync_meta(...)`
— calling a private helper across module boundary. Works correctly but
breaks encapsulation. A small public wrapper or using `push_to_jira` for
the meta-write path would be cleaner. Non-blocking.

ISSUES_TOTAL=1 ISSUES_BLOCKING=0

---

## Performance

No issues. Managed-mode reads are gated behind mode check and ticket filter.
auto-push for non-managed sources (abort/jump) unchanged from before.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

---

## Test coverage

22 core tests + 16 managed tests — all passing. All blocking coverage gaps
from previous review now addressed:
- HTTPS validation, missing mapping, non-list managed_tickets
- Full FakeJiraClient method coverage (get_transitions, transition_issue,
  get_current_user, make_client)
- Artifact URL format assertion
- status match/mismatch with read-only verification
- reconcile push delegates to jira_sync.push()
- sync --apply clears stale conflicts
- issue-missing recorded in meta
- abort source skips managed prompt

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

---

## Verdict

**APPROVED** — all 11 blocking findings from KLC-020 and KLC-021 reviews
resolved. ONE LOW finding (private helper call) is a cleanup for a follow-up.
38 tests pass. DOCTOR_OK.


---
[!CONFLICT] scope-expansion detected at review:ack-needed
  planned modules: ['jira_sync', 'lifecycle', 'jira', 'jira_config', 'doctor', 'validate_config', 'config', 'docs', 'tests', 'tickets', 'knowledge', 'index']
  actual modules:  ['config', 'docs', 'doctor', 'index', 'intake', 'jira', 'jira_artifacts', 'jira_config', 'jira_sync', 'knowledge', 'lifecycle', 'tests', 'tickets', 'validate_config']
  unplanned:       ['intake', 'jira_artifacts']
Resolve: update meta.json:affected_modules to include all touched modules, then re-run `klc ack KLC-021`.
