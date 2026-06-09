---
ticket: KLC-022
kind: feature
authority: agent
---

# KLC-022 — Detailed test plan (post-design)

## Step 1: lifecycle.jira_pull()

| # | Test | How |
|---|------|-----|
| 1.1 | jira-pull event written | `jira_pull(ticket, "build", jira_status="In Progress")` → phase_history has event=jira-pull |
| 1.2 | event fields correct | event has jira_status, target_phase, missing_artifacts=[], skipped_phases=[] |
| 1.3 | jira-force-pull event when force=True | `jira_pull(..., force=True, reason="x")` → event=jira-force-pull, note="x" |
| 1.4 | klc moves to target:work | meta.phase == "build:work" |

## Step 2: jira_sync.pull()

| # | Test | How |
|---|------|-----|
| 2.1 | pull disabled → error | integration disabled → ok=False, action=disabled |
| 2.2 | forward pull, all inputs present | ticket at discovery-lite:ack, inputs on disk → ok=True, advances to target |
| 2.3 | forward pull skips conditional phase | ticket with risk_tags=[], pull --to archived → observe in skipped_phases |
| 2.4 | forward pull stops at missing inputs | build-log.md absent, pull --to review → ok=False, missing_artifacts=[build-log.md] |
| 2.5 | force=True bypasses missing inputs | same as 2.4 but force=True → ok=True, build-log.md in event.missing_artifacts |
| 2.6 | backward pull supersedes downstream | ticket at review:work, pull --to build → supersede_phases called for [review] |
| 2.7 | backward pull calls jira_pull | jira-pull event in phase_history |
| 2.8 | direction detection: forward | index(target) > index(current) → direction=forward |
| 2.9 | direction detection: backward | index(target) < index(current) → direction=backward |
| 2.10 | target not in jira_to_klc[status] → error | `--to review` when Jira="In Progress" (review not in candidates) → ok=False, error lists candidates |
| 2.11 | target not in track → error | S-track, `--to design` → ok=False |

## Step 3: CLI reconcile pull/force-pull

| # | Test | How |
|---|------|-----|
| 3.1 | pull --to missing arg → usage error | `reconcile KLC-X pull` without --to → exit non-zero |
| 3.2 | pull --to invalid phase → error | phase not in jira_to_klc → exit 1 with candidates |
| 3.3 | pull --to valid, ok=True → exit 0 | FakeJiraClient, all inputs present → exit 0 |
| 3.4 | pull --to valid, missing inputs → shows two sections | SKIPPED and MISSING sections in output |
| 3.5 | force-pull --reason writes event | event.note == reason |
| 3.6 | backward pull non-TTY → abort | isatty=False, backward direction → exit 1 with message |

## Step 4: inline rework fork in _prompt_conflict

| # | Test | How |
|---|------|-----|
| 4.1 | backward PM-move shows pull candidates | mock TTY, plan with jira-moved-externally + backward → option 1 shows candidates |
| 4.2 | pick 1 → pull executed | stdin="1\n<candidate>\ny" → pull called |
| 4.3 | pick 2 → push back (unchanged from KLC-021) | stdin="2" → push called |
| 4.4 | pick 3 → conflict recorded (unchanged) | stdin="3" → conflict in meta |

## Edge cases

| # | Scenario | Expected |
|---|----------|---------|
| E-1 | pull --to current phase | noop, ok=True, action=noop |
| E-2 | Jira unreachable during pull | ok=False, error, klc unchanged |
| E-3 | e2e pipeline all tracks | all pass (pull is explicit-only, no regression) |
| E-4 | force-pull to archived | ok=True, full skip list in event |
