# Agent prompt — KLC-022 · build:work · step-1

Ticket: **KLC-022** · track: **M** · kind: **feature**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Add jira→klc state movement: `pull` (forward & backward) and `force-pull`.
Always human-chosen, klc validates. When the PM moves Jira (forward or in
rework), the human reconciles klc to match — picking from valid candidates,
never guessing. Part 3 of 3. Depends on KLC-021.

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

### Current step — step-1

**lifecycle.jira_pull() dedicated op**

New low-level operation in `core/skills/lifecycle.py`.
Does NOT route through ack/picks. Writes provenance event to phase_history.


**Changes**:
```python
def jira_pull(ticket: str, target_phase: str, *,
              jira_status: str,
              force: bool = False,
              reason: str | None = None,
              missing_artifacts: list[str] | None = None,
              skipped_phases: list[str] | None = None) -> str:
    """Move klc to target_phase with Jira provenance. Returns new phase string."""
    event = "jira-force-pull" if force else "jira-pull"
    extra = {
        "jira_status": jira_status,
        "target_phase": target_phase,
        "missing_artifacts": missing_artifacts or [],
        "skipped_phases": skipped_phases or [],
    }
    if reason:
        extra["note"] = reason
    set_state(ticket, target_phase, STATE_WORK, event=event, extra=extra)
    return format_state(target_phase, STATE_WORK)
```

**Affected files**:


**Expected tests**:



**Rollback**: delete function


### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/mnt/d/a_work/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-022 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-022/impl-plan.md`
- Full spec: `.klc/tickets/KLC-022/spec.md`
- Full test-plan: `.klc/tickets/KLC-022/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-022 step-1` and
run `klc step KLC-022 2` to get the next step's card,
or `klc ack KLC-022 --pick 1` if this was the last step.
