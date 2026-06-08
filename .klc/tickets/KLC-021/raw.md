---
ticket: KLC-021
kind_hint: feature
created: 2026-06-05T10:22:29Z
---
Jira integration — managed mode + push. Part 2 of 3. Depends on KLC-020.

Add interactive state sync. The core principle: choice at the decision point, inline — never deferred.

- config: add `mode: mirror | managed` and optional `managed_tickets: [KEY]`.
- core/skills/jira_sync.py: extend with build_plan(ticket) -> SyncPlan (side-effect-free: compares klc phase vs jira status via status_mapping, lists fields to update, transition needed, conflicts). push(ticket) -> Result (move Jira to match klc phase; single-hop only; if no direct transition → record conflict transition-blocked, show manual action; never move klc).
- INTERACTIVE hook: core/skills/lifecycle.py:137 push_phase becomes mode-aware.
    mirror → auto-push as today (unchanged).
    managed + TTY → on ack/next, detect divergence; if klc moved → prompt: 1) push Jira to match (recommended) 2) leave as-is. If PM moved Jira manually (current != last_jira_status and != target) → CONFLICT prompt: 1) push Jira back (klc wins) 2) keep Jira, record divergence 3) skip — write [!CONFLICT] to meta, show in doctor.
    managed + non-TTY → default "record divergence, don't touch Jira" + stderr warning. NEVER push silently.
    Only ack/next prompt; klc jira status stays read-only.
- `klc jira sync <KEY> --dry-run|--apply`: report mismatch, add/update artefact links, update meta.json:jira_sync. State change is NOT done by sync — only via reconcile (separate command).
- `klc jira reconcile <KEY> push`: explicit push entry point (for when human is not on ack).
- meta.json:jira_sync block: {enabled, issue_key, last_synced_at, last_jira_status, last_klc_phase (FULL phase:state), last_action, conflicts:[{type, detail, detected_at, suggested}]}. conflict types: jira-moved-externally | transition-blocked | required-field | issue-missing.
- klc doctor: surface meta.jira_sync.conflicts.
- "moved by klc" comment on every klc-initiated transition.

NOT in this ticket: pull/force-pull (KLC-022).

See memory project-jira-integration for full design.
