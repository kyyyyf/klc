# Agent prompt — KLC-019 · build:work · step-1

Ticket: **KLC-019** · track: **S** · kind: **bug**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Make `profile.yml` contract unambiguous: the file selects only the active
profile name. Remove the undocumented `languages` override from
`detect_languages.py` and confirm the validator, code, and docs all agree.

## Acceptance Criteria

- [ ] AC-1: `detect_languages.py` no longer reads `languages` from `profile.yml`.
  Language detection uses only `inventory.json` threshold logic.
- [ ] AC-2: `validate_config.py` schema for `profile.yml` stays as `{"profile"}` —
  no change needed (it was already correct; test confirms it).
- [ ] AC-3: `klc doctor` passes with no warnings on the current `config/profile.yml`.
- [ ] AC-4: `detect_languages.py` docstring and module comment updated to remove
  references to `profile.yml` language override.
- [ ] AC-5: `docs/process.md` (or relevant doc) updated — no mention of `languages`
  in `profile.yml` as a valid key.

### Current step — step-1

**step-1**



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
re-run `klc step KLC-019 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-019/impl-plan.md`
- Full spec: `.klc/tickets/KLC-019/spec.md`
- Full test-plan: `.klc/tickets/KLC-019/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-019 step-1` and
run `klc step KLC-019 2` to get the next step's card,
or `klc ack KLC-019 --pick 1` if this was the last step.
