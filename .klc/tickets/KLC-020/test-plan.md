---
ticket: KLC-020
kind: feature
authority: agent
---

# KLC-020 — Detailed test plan (post-design)

## Acceptance coverage

### Step 1: jira.yml + validate_config

| # | Test | How |
|---|------|-----|
| 1.1 | New keys accepted | `validate_config.validate_file(config/jira.yml)` → no warnings |
| 1.2 | klc doctor passes | `python3 core/phases/doctor.py` → DOCTOR_OK |
| 1.3 | Unknown key rejected | synthetic jira.yml with `unknown_key: x` → warning |
| 1.4 | mode key accepted | jira.yml with `mode: mirror` → no warnings |

### Step 2: jira_config.py

| # | Test | How |
|---|------|-----|
| 2.1 | Valid config loads | `jira_config.load(config_dir)` → JiraConfig, no exception |
| 2.2 | Missing base_url | config without `site.base_url` → JiraConfigError with "base_url" |
| 2.3 | Missing auth_env | config without `site.auth_env` → JiraConfigError |
| 2.4 | Missing klc_to_jira | config without `status_mapping.klc_to_jira` → JiraConfigError |
| 2.5 | Missing jira_to_klc | config without `status_mapping.jira_to_klc` → JiraConfigError |
| 2.6 | Malformed blob_url | template missing `{path}` → JiraConfigError |
| 2.7 | Branch auto-detect | empty `gitlab.branch`, git available → branch from git |

### Step 3: jira_client.py

| # | Test | How |
|---|------|-----|
| 3.1 | FakeJiraClient.get_issue | returns canned issue, records call |
| 3.2 | FakeJiraClient.get_transitions | returns canned list |
| 3.3 | FakeJiraClient.add_comment | records call, returns synthetic response |
| 3.4 | FakeJiraClient.update_comment | records call |
| 3.5 | FakeJiraClient.get_issue_comments | returns canned comments |
| 3.6 | FakeJiraClient.get_current_user | returns canned user |
| 3.7 | RestJiraClient missing auth env | raises RuntimeError naming env var |
| 3.8 | make_client with enabled config | returns RestJiraClient |

### Step 4: jira_artifacts.py

| # | Test | How |
|---|------|-----|
| 4.1 | Existing artefacts in table | ticket with spec.md, build-log.md; test-plan.md absent → spec.md and build-log.md in output, test-plan.md omitted |
| 4.2 | No artefacts | empty ticket dir → no error, empty/minimal output |
| 4.3 | GitLab URL format | URL matches `{base_url}/-/blob/{branch}/{path}` exactly |
| 4.4 | upsert first call | FakeJiraClient has no existing comment → add_comment called once |
| 4.5 | upsert second call | FakeJiraClient has comment with marker → update_comment called, NOT add_comment |
| 4.6 | Marker format | comment body contains `<!-- klc:artifact-links KEY -->` |

### Step 5: klc jira status + sync

| # | Test | How |
|---|------|-----|
| 5.1 | status, matching | FakeJiraClient returns "In Review"; klc at review:work; klc_to_jira[review]="In Review" → exit 0, no MISMATCH |
| 5.2 | status, mismatch | Jira at "In Progress"; klc at review:work → exit 1, MISMATCH line in stdout |
| 5.3 | status, disabled | integration disabled → error message, exit non-zero |
| 5.4 | sync --dry-run | FakeJiraClient → plan printed, no write calls recorded |
| 5.5 | sync --apply | FakeJiraClient → upsert called, meta.jira_sync written |
| 5.6 | No subcommand | `klc jira` with no args → usage printed, exit non-zero |

### Step 6: intake dup-check

| # | Test | How |
|---|------|-----|
| 6.1 | --jira-description klc | FakeJiraClient has issue; raw.md has klc desc, NO klc:jira-description markers |
| 6.2 | --jira-description jira | raw.md contains `<!-- klc:jira-description KEY -->` + Jira body + closing marker |
| 6.3 | --jira-description both | raw.md has klc desc first, then Jira marker section |
| 6.4 | Jira 404 | FakeJiraClient raises 404; intake succeeds; warning in stderr |
| 6.5 | Jira 403 | FakeJiraClient raises 403; intake succeeds; warning in stderr |
| 6.6 | Integration disabled | no Jira calls; intake proceeds normally |
| 6.7 | Non-TTY without flag | default=klc; warning to stderr |

### Step 7: intake raw.md link comment

| # | Test | How |
|---|------|-----|
| 7.1 | Comment added | FakeJiraClient; intake with integration enabled → add_comment called once |
| 7.2 | Comment body has raw.md URL | comment contains raw.md blob URL |
| 7.3 | Comment body has provenance | comment contains "moved by klc" |
| 7.4 | Idempotent | second intake on same key → update_comment, not second add_comment |

## Edge cases

| # | Scenario | Expected |
|---|----------|---------|
| E-1 | `klc jira` no subcommand | usage + exit non-zero |
| E-2 | status, Jira timeout | error printed; meta.jira_sync NOT modified |
| E-3 | E2E pipeline runs | all 4 tracks + negative + conditional still PASS (no regression) |
| E-4 | doctor with new jira.yml keys | DOCTOR_OK |
| E-5 | jira_to_klc entry has empty list | `jira_config.load()` succeeds (valid; pull not possible for that status) |
