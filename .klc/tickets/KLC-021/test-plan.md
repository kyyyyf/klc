---
ticket: KLC-021
kind: feature
authority: agent
---

# KLC-021 — Detailed test plan (post-design)

## Acceptance coverage

### Step 1: config

| # | Test | How |
|---|------|-----|
| 1.1 | managed_tickets accepted | validate_config on jira.yml with managed_tickets: [K-1] → no warnings |
| 1.2 | empty managed_tickets accepted | managed_tickets: [] → no warnings |
| 1.3 | doctor passes | DOCTOR_OK |

### Step 2: build_plan()

| # | Test | How |
|---|------|-----|
| 2.1 | In-sync | FakeClient Jira="In Review"; klc phase=review:work; last_jira="In Review" → in_sync=True, no conflicts |
| 2.2 | klc moved forward | Jira="In Progress"; klc=review:work → in_sync=False, target_status="In Review" |
| 2.3 | PM moved externally | last_jira="In Progress", current Jira="Done", klc=build:work → conflict type=jira-moved-externally |
| 2.4 | Issue 404 | FakeClient raises 404 → conflict type=issue-missing |
| 2.5 | No network writes | FakeClient.calls contains only GET-equivalent (get_issue, get_transitions) — no add_comment or transition_issue |

### Step 3: push()

| # | Test | How |
|---|------|-----|
| 3.1 | Transition found → executed | FakeClient has matching transition → transition_issue called once |
| 3.2 | "moved by klc" comment | add_comment called with "moved by klc" after transition |
| 3.3 | Idempotent: already at target | FakeClient Jira already "In Review"; klc=review → no transition_issue call |
| 3.4 | No transition found | FakeClient returns empty transitions → no transition_issue; conflict transition-blocked returned |
| 3.5 | Jira unreachable | FakeClient.transition_issue raises RuntimeError → result ok=False, no crash |

### Step 4: lifecycle.push_phase mode-aware

| # | Test | How |
|---|------|-----|
| 4.1 | mirror mode unchanged | mode=mirror, FakeClient → push called automatically (regression: e2e all tracks pass) |
| 4.2 | managed in-sync → silent | managed, FakeClient Jira="In Review", klc=review → no prompt, no push |
| 4.3 | managed TTY klc-moved pick 1 | mock isatty=True, stdin="1" → push called |
| 4.4 | managed TTY klc-moved pick 2 | mock isatty=True, stdin="2" → no push, no conflict recorded |
| 4.5 | managed TTY PM-conflict pick 1 | mock isatty=True, conflict plan, stdin="1" → push back called |
| 4.6 | managed TTY PM-conflict pick 2 | mock isatty=True, stdin="2" → meta.jira_sync.conflicts has jira-moved-externally |
| 4.7 | managed TTY PM-conflict pick 3 | mock isatty=True, stdin="3" → meta.jira_sync.conflicts has entry |
| 4.8 | managed non-TTY divergence | isatty=False, Jira!=target → no push, conflict in meta, stderr warning |
| 4.9 | managed non-TTY in-sync | isatty=False, Jira==target → silent, no prompt, no conflict |
| 4.10 | Jira unreachable in managed | FakeClient raises → ack completes (no exception), warning on stderr |
| 4.11 | managed_tickets=[OTHER], ticket not in list | ticket KLC-X not in list → mirror behaviour |

### Step 5: doctor jira-sync-conflicts

| # | Test | How |
|---|------|-----|
| 5.1 | Ticket with conflict → WARN | meta.jira_sync.conflicts non-empty → doctor shows WARN jira-sync-conflicts |
| 5.2 | No conflicts → PASS | conflicts=[] → jira-sync-conflicts PASS |
| 5.3 | No jira_sync key → PASS | meta without jira_sync → no error |

## Edge cases

| # | Scenario | Expected |
|---|----------|---------|
| E-1 | integration enabled, JIRA_API_TOKEN unset → push_phase | ack completes; "[jira-sync] warning" on stderr |
| E-2 | mode=managed, managed_tickets=[] (all) | all tickets go through managed flow |
| E-3 | e2e pipeline all tracks (default config: disabled) | PASSED, no Jira interaction |
| E-4 | push_phase called during abort/jump | still non-blocking |
