---
ticket: KLC-022
kind: feature
authority: human
last_generated: 2026-06-05
risk_tags: [user-facing]
---

# KLC-022 — Jira integration: reconcile pull + force-pull

## Goals

Add jira→klc state movement: `pull` (forward & backward) and `force-pull`.
Always human-chosen, klc validates. When the PM moves Jira (forward or in
rework), the human reconciles klc to match — picking from valid candidates,
never guessing. Part 3 of 3. Depends on KLC-021.

## Problem / Context

KLC-021 handles klc→Jira (push) and divergence detection. The reverse —
PM moved Jira, klc must follow — is pull. Forward pull (PM advanced) and
backward pull (PM rejected = rework) have DIFFERENT mechanics:
forward = inputs-check + conditional-skip walk; backward = supersede
downstream. Both behind one `pull --to` command, direction auto-detected
by phase index ([!DECISION D-001]).

[!DECISION D-001] `--to` is explicit and required. klc validates
`target ∈ jira_to_klc[status]` and detects direction by phase index in track.
[!DECISION D-002] forward pull reuses advance_to_next walk → respects
conditional skips (KLC-014). missing inputs → stop, suggest force-pull.
[!DECISION D-003] backward pull supersedes downstream artefacts (reuse
lifecycle supersede), confirm before superseding.
[!DECISION D-004] force-pull / skips write structured phase_history events
for later retro tooling — skip with warning is the human's call.

## Acceptance Criteria

1. AC-1: `jira_sync.pull(ticket, target_phase, force=False, reason=None) -> Result`.
2. AC-2: `klc jira reconcile <KEY> pull --to <phase>`:
   (a) read Jira status; (b) validate `--to ∈ jira_to_klc[status]` else error
   listing valid candidates; (c) validate `--to` applies to ticket track;
   (d) determine direction by phase index.
3. AC-3: FORWARD pull (`--to` later than current) walks advance-style,
   RESPECTING conditional skips (condition=False → skip, event=skipped).
   A crossed phase with required inputs missing → STOP, suggest force-pull.
4. AC-4: BACKWARD pull (`--to` earlier) supersedes downstream artefacts via
   lifecycle supersede; confirm before superseding; moves klc back.
5. AC-5: pull uses a DEDICATED lifecycle operation (not the normal ack path)
   that records the jump with jira provenance.
6. AC-6: `klc jira reconcile <KEY> force-pull --to <phase> --reason "..."`
   moves klc ignoring missing artefacts; writes phase_history event
   `{event: jira-force-pull, note: reason, jira_status, target_phase,
   missing_artifacts:[], skipped_phases:[]}`.
7. AC-7: INLINE rework fork — when ack/next (KLC-021) detects PM moved Jira
   BACKWARD, the prompt offers: 1) accept rework: pull to a candidate from
   jira_to_klc (supersedes downstream, asks confirm) 2) reject: push Jira back
   3) skip. Human picks a valid target from the list — no phase-name guessing.
8. AC-8: forward pull through a missing-inputs phase clearly distinguishes
   conditional-skipped steps (legitimate) from artefact-missing steps
   (require force), then human chooses proceed(force)/cancel.

## Non-goals

- AC-flow from Jira (own later ticket).
- create_missing_issue (rare path, deferred).
- multi-hop Jira transitions (single-hop + conflict).
- `klc audit --forced-pulls` retro tooling (deferred; this ticket only writes
  the structured events it will consume).

## Affected modules

- `core/skills/jira_sync.py` — pull, force-pull, direction detection
- `core/skills/lifecycle.py` — dedicated pull operation (jump-with-provenance)
- `core/phases/jira.py` — reconcile pull/force-pull subcommands
- `tests/integration/` — forward/backward pull, conditional skip, missing
  inputs, force-pull audit event, rework fork
- `docs/process.md` — reconcile pull semantics, force-pull audit

## Open questions

None blocking. Backward detection: `track_phases(track).index(target) <
.index(current)`.

## Estimate

- complexity: 3 (two mechanics under one command, lifecycle op, conditional interplay)
- uncertainty: 2 (supersede + conditional-skip interaction edge cases)
- risk: 2 (moves klc state backward — must be auditable and confirmed)
- manual: 1 (verify rework round-trip against real Jira)
- total: 8 → **M**
