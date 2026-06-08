---
ticket: KLC-021
phase: build
authority: agent
---

# KLC-021 build log — rework pass (addressing review findings)

## Original build (steps 1-5): see build-log.md in ticket root

## Rework — addressing KLC-020 + KLC-021 review findings

### KLC-021 HIGH-1 fixed: managed hook restricted to ack/next sources
`_jira_push_after_state` now gates managed-mode prompts on
`_MANAGED_SOURCES = {"ack", "advance", "set_state"}`. abort/jump use
mirror auto-push only — they are internal operations, not decision points.
New test: `test_managed_hook_skips_on_abort_source`.

### KLC-021 HIGH-2 fixed: public `jira_sync.push(ticket)` wrapper added
`push(ticket)` loads config/client internally and delegates to
`push_to_jira`. This is the canonical entry point per spec AC-3.

### KLC-021 HIGH-3 fixed: `_reconcile_push` now delegates to `jira_sync.push()`
Removed duplicated transition/comment/meta logic from `jira.py`. 
`_reconcile_push` → `jira_sync.push(key)` → single authoritative path.
`_update_meta_jira_sync` and `_write_conflict` helpers removed from jira.py.
New test: `test_reconcile_push_delegates_to_push_to_jira`.

### KLC-021 HIGH-4 fixed: issue-missing/unreachable recorded in meta
`push_to_jira` now calls `_record_conflict_in_meta` for issue-missing and
jira-unreachable before returning error.
New test: `test_issue_missing_recorded_in_meta`.

### KLC-021 HIGH-5 fixed: successful push/sync clears stale conflicts
`_update_jira_sync_meta(clear_conflicts=True)` called on success.
`cmd_sync --apply` clears conflicts when Jira is in sync.
New test: `test_sync_apply_clears_conflicts_on_success`.

### KLC-021 MEDIUM fixed: managed_tickets non-list raises JiraConfigError
`jira_config.load()` now validates type and gives a clear error message.

### KLC-020 HIGH-1 fixed: HTTPS required for site.base_url
`jira_config.load()` validates scheme == "https" and hostname present.
New test: `test_jira_config_https_required`.

### KLC-020 HIGH-2 fixed: legacy phase_to_status restored to original values
`sync.phase_to_status` reverted to original Jira status names to avoid
breaking existing mirror-mode setups.

### KLC-020 HIGH-4 fixed: upsert_artifact_links safe on comment-read failure
`_find_link_comment` now raises `_CommentReadError` on RuntimeError.
`upsert_artifact_links` catches it and skips write (logs warning instead
of blindly calling add_comment which would duplicate the marker).
New test: `test_upsert_skips_write_on_comment_read_failure`.

### KLC-020 HIGH-5..9 fixed: missing test coverage added
New tests in test_jira_core.py (22 total, was 12):
- https required, missing klc_to_jira, non-list managed_tickets
- FakeJiraClient: get_transitions, transition_issue, get_current_user
- make_client returns RestJiraClient
- artifact URL format assertion
- status match/mismatch with read-only verification

### KLC-020 MEDIUM-1 fixed: path traversal guard in jira_artifacts.py
Resolved path must start with ticket_dir.resolve() — rejects `..` traversal.

### KLC-020 MEDIUM-2 fixed: 403/timeout distinguished from 404 in intake
intake.py now returns early on non-404 Jira errors with a clear warning,
instead of silently treating all errors as "issue not found".

All checks: DOCTOR_OK, smoke OK, e2e 4 tracks + negative + conditional,
22 core tests, 16 managed tests — ALL PASSED.
