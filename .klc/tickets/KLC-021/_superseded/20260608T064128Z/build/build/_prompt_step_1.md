# Agent prompt — KLC-021 · build:work · step-1

Ticket: **KLC-021** · track: **M** · kind: **feature**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Add interactive state sync (klc→Jira) with the core principle: **choice at
the decision point, inline — never deferred**. Introduce `mode: managed`
where the lifecycle hook detects divergence at ack/next and prompts the
human in the same command. Part 2 of 3. Depends on KLC-020.

## Acceptance Criteria

1. AC-1: `config/jira.yml` gains `mode: mirror|managed` and optional
   `managed_tickets: [KEY]`. validate_config + doctor pass.
2. AC-2: `jira_sync.build_plan(ticket) -> SyncPlan` — side-effect-free.
   Compares klc phase vs Jira status via status_mapping; lists target status,
   transition needed, conflicts. No network writes.
3. AC-3: `jira_sync.push(ticket) -> Result` — moves Jira to match klc phase,
   single-hop only. No direct transition → record conflict
   `transition-blocked`, show manual action, never move klc.
4. AC-4: `lifecycle.push_phase` is mode-aware:
   - mirror → auto-push as today (unchanged regression-tested);
   - managed + TTY, klc moved → prompt: 1) push Jira to match (recommended)
     2) leave as-is;
   - managed + TTY, PM moved Jira manually (current != last_jira_status AND
     != target) → CONFLICT prompt: 1) push Jira back (klc wins) 2) keep Jira,
     record divergence 3) skip — write [!CONFLICT] to meta, show in doctor;
   - managed + non-TTY → record divergence, no Jira write, stderr warning.
5. AC-5: `klc jira sync <KEY> --dry-run|--apply` — reports mismatch, adds/updates
   idempotent artefact links, updates meta.json:jira_sync. Does NOT change phase
   state.
6. AC-6: `klc jira reconcile <KEY> push` — explicit push entry point for when
   the human is not at ack.
7. AC-7: meta.json:jira_sync block written:
   `{enabled, issue_key, last_synced_at, last_jira_status,
   last_klc_phase (FULL phase:state), last_action, conflicts:[...]}`.
   conflict types: jira-moved-externally | transition-blocked | required-field |
   issue-missing.
8. AC-8: `klc doctor` surfaces meta.jira_sync.conflicts.

### Current step — step-1

**config: managed_tickets + validate_config**

Add `managed_tickets` optional list to `config/jira.yml`.
Update `validate_config.py` KNOWN_SCHEMAS["jira.yml"].

**Affected files**:


**Expected tests**:



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
re-run `klc step KLC-021 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-021/impl-plan.md`
- Full spec: `.klc/tickets/KLC-021/spec.md`
- Full test-plan: `.klc/tickets/KLC-021/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-021 step-1` and
run `klc step KLC-021 2` to get the next step's card,
or `klc ack KLC-021 --pick 1` if this was the last step.
