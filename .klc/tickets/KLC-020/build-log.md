---
ticket: KLC-020
phase: build
authority: agent
---

# KLC-020 build log

## Steps completed

**step-1** — jira.yml + validate_config.py: green
Extended jira.yml with site/gitlab/status_mapping/artifacts/mode sections.
Added all new keys to validate_config KNOWN_SCHEMAS["jira.yml"]. DOCTOR_OK.

**step-2** — jira_config.py: green
JiraConfig dataclass + load() with validation. Guards against core/shared/yaml.py
shadowing pyyaml by temporarily removing it from sys.path.

**step-3** — jira_client.py: green
JiraClient protocol, RestJiraClient (urllib, no extra deps), FakeJiraClient
(in-memory, records calls), make_client() factory.

**step-4** — jira_artifacts.py: green
build_artifact_links() — GitLab blob URLs for existing files only.
upsert_artifact_links() — idempotent: finds marker comment, updates vs creates.

**step-5** — core/phases/jira.py + scripts/klc: green
klc jira status (read-only), sync (--dry-run|--apply), reconcile push.
Registered jira in OPERATIONAL_CMDS.

**step-6** — intake.py dup-check: green
--jira-description flag + TTY prompt. Jira body in markers.
_jira_intake_enrich() — non-blocking (warnings only on Jira errors).

**step-7** — test_jira_core.py + docs: green
12 integration tests, all passing with FakeJiraClient (zero network).
docs/process.md: new Jira integration section with setup, commands, meta block.

**All checks**: DOCTOR_OK, smoke OK, e2e all tracks + negative + conditional PASSED.
12/12 integration tests passed.
