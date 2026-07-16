---
ticket: KLC-065
kind_hint: tech
created: 2026-07-16T15:38:08Z
---
Wrap 'jira sync --apply' so meta.jira_sync is committed and CAS-pushed via state_tx under feature-ON. Today _update_jira_sync_meta writes meta.json locally with no state_tx, so the drift-tracking bookkeeping only reaches origin when a later verb runs and can be stranded in a stash on a pull_rebase_preserving conflict. Deferred from KLC-061 Q-002 (both reviewers judged it acceptable as advisory drift-tracking, not lifecycle state). Low priority: same unwrapped-mutation class as KLC-061 but for the advisory jira_sync field only.
