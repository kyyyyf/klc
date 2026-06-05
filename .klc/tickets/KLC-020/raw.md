---
ticket: KLC-020
kind_hint: feature
created: 2026-06-05T10:18:58Z
---
Jira integration MVP — read-only core + enrich. Part 1 of 3 (KLC-020/021/022).

Build the side-effect-free foundation of the `klc jira` namespace:

- config/jira.yml: extend with site.project_key, gitlab.blob_url template, status_mapping (klc_to_jira + jira_to_klc candidate lists), artifacts.paths, mode (mirror|managed). Update validate_config.py schema.
- core/skills/jira_config.py (new): load + validate jira.yml. Validate enabled, base_url, auth_env, both mappings present and consistent, gitlab URL templates.
- core/skills/jira_client.py (new): thin fakeable REST client — get_issue, get_transitions, transition_issue, add_comment, get_current_user. Must be mockable for tests with no network.
- core/skills/jira_artifacts.py (new): build GitLab blob links for EXISTING klc artefacts only (per artifacts.paths). Return comment-ready link table. Do NOT upload files.
- core/phases/jira.py (new): CLI wrapper. Implement `klc jira status <KEY>` — READ-ONLY, no prompts, no network state change. Prints klc phase vs Jira status, mismatch if any.
- scripts/klc: register `jira` subcommand.
- intake dup-check: when integration enabled and `klc intake <KEY>` runs, GET issue by key (== klc key always). If exists → inline warning + choose description source (1=klc, 2=jira, 3=both); flags --jira-description klc|jira|both for non-interactive. Jira description stored in raw.md inside markers <!-- klc:jira-description KEY -->...<!-- /klc:jira-description -->. Always add Jira comment with GitLab link to raw.md. "moved by klc" provenance on any klc-initiated comment.
- idempotent artefact-links: re-running sync must UPDATE the existing link comment (marker-based), not duplicate it.

NOT in this ticket: push/pull state changes (KLC-021/022), managed-mode hook, AC handling.

See memory project-jira-integration for full design.
