---
ticket: KLC-022
kind_hint: feature
created: 2026-06-05T11:56:54Z
---
Jira integration — reconcile pull (forward/backward) + force-pull. Part 3 of 3. Depends on KLC-021.

Add jira→klc state movement, always human-chosen, klc validates.

- core/skills/jira_sync.py: pull(ticket, target_phase, force=False, reason=None) -> Result.
- `klc jira reconcile <KEY> pull --to <phase>`:
    1. Read current Jira status. 2. Validate --to ∈ jira_to_klc[status] (else error, show valid candidates). 3. Validate --to applies to ticket track. 4. Determine direction by phase index in track:
       FORWARD (--to later than current): walk advance-style, RESPECTING conditional skips (KLC-014: condition=False → skip with event=skipped). If a crossed phase has required inputs missing → STOP, suggest force-pull.
       BACKWARD (--to earlier): supersede downstream artefacts (reuse lifecycle supersede), move klc back. Confirm before supersede.
    5. Move klc via a DEDICATED lifecycle operation (not normal ack path) that records the jump.
- `klc jira reconcile <KEY> force-pull --to <phase> --reason "..."`: move klc to target ignoring missing artefacts. MUST write phase_history event: {event: jira-force-pull, note: reason, jira_status, target_phase, missing_artifacts:[], skipped_phases:[]}. Forced moves visible in audit.
- INLINE forks: when ack/next (KLC-021) detects PM moved Jira BACKWARD (rework), prompt offers: 1) accept rework: pull --to <build candidate> (supersedes downstream, asks confirm) 2) reject: push Jira back 3) skip. Human picks valid target from jira_to_klc list — no guessing phase names.
- P5 skip-with-warning: forward-pull through missing-inputs phase warns clearly which steps lack artefacts (vs which are conditional-skipped legitimately), then human chooses proceed(force)/cancel.

NOT in this ticket: AC-flow, create_missing_issue, multi-hop transitions, `klc audit --forced-pulls` retro tooling (all deferred).

See memory project-jira-integration for full design.
