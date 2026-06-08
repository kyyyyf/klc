---
ticket: KLC-021
phase: build
authority: agent
---

# KLC-021 build log

**step-1** green: managed_tickets in jira.yml + validate_config; JiraConfig.is_managed_ticket()

**step-2** green: SyncPlan dataclass; build_plan() pure-read; push_to_jira() single-hop
with transition + "moved by klc" comment; _record_conflict_in_meta / _update_jira_sync_meta helpers

**step-3** green: lifecycle._jira_push_after_state() mode dispatcher;
mirror=legacy push_phase (unchanged); managed=_managed_jira_push (TTY/non-TTY);
prompts: klc-moved (2-option) and PM-conflict (3-option); non-TTY records divergence silently

**step-4** green: doctor jira-sync-conflicts check (warn-only); refactored
project-tools warn logic into _WARN_ONLY set

**step-5** green: 12 integration tests (FakeJiraClient, mocked TTY);
docs/process.md managed mode section added

All checks: DOCTOR_OK, smoke OK, e2e all tracks + negative + conditional PASSED
12/12 managed tests + 12/12 core tests PASSED
