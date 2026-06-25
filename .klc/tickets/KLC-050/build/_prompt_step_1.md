# Agent prompt — KLC-050 · build:work · step-1

Ticket: **KLC-050** · track: **S** · kind: **tech**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Close the four judgment-side gate weaknesses the 2026-06-24 quality review found, so the
gates resist trivial bypass rather than matching only one canonical shape. Four small,
independent fixes: broaden the no-pre-judgment lint, reject placeholder picks, make the
model-on-subagent guard actually reject, and unify the duplicate step parser plus retire the
stale plan templates.

## Acceptance Criteria

- [ ] AC-1: `lint_review_prompts.lint_text` flags `don't flag this`, `ignore this issue`,
  `treat as minor`, and `downgrade it`; negative fixtures confirm benign review prose is not
  flagged.
- [ ] AC-2: `spec_structure.recorded_pick` returns False for a placeholder pick
  (`Picked: <approach>` / `Picked: TBD`) and True only for a concrete pick.
- [ ] AC-3: `model_guard` exposes a strict path that returns a rejection (non-zero / raised)
  when a subagent dispatch has no resolved model; the build/runner dispatch paths consult it
  and refuse rather than only printing a note.
- [ ] AC-4: A single `## step-N` parser is used by both `phase_completion` and
  `impl_plan_check` (one removed in favour of the other); a test asserts they agree on a
  sample plan.
- [ ] AC-5: The stale `core/templates/impl-plan.md.j2` / `impl-plan-short.md.j2` are either
  removed or updated to carry the gate-required fields; a test asserts any shipped plan
  template renders a gate-passing skeleton.

### Current step — step-1

**broaden the no-pre-judgment lint**

- **Goal:** catch contractions and paraphrases of pre-judgment directives. (AC-1)
- RED: add `test_lint_catches_paraphrases` + `test_lint_ignores_benign` to
  `tests/integration/test_no_pre_judgment_lint.py`. Fails today (narrow patterns).
- **Interfaces:** extend `_PATTERNS` in `core/skills/lint_review_prompts.py` to cover
  `don'?t flag`, `ignore (this|the) (issue|finding|file)`, `treat .*as (minor|trivial)`,
  `downgrade (it|this|the severity)`.
- **Expected:** the four phrasings are flagged; benign prose ("should not ignore edge cases")
  is not.
- **VERIFY:** `python3 -m pytest tests/integration/test_no_pre_judgment_lint.py -q`
- **COMMIT:** `KLC-050 step-1: broaden no-pre-judgment lint to contractions and paraphrases`
- **Affected:** `core/skills/lint_review_prompts.py`,
  `tests/integration/test_no_pre_judgment_lint.py`.
- Depends-on: none.
- **Code sketch:**

```python
_PATTERNS += [
    re.compile(r"(?i)don'?t\s+flag"),
    re.compile(r"(?i)ignore\s+(this|the)\s+(issue|finding|file)"),
    re.compile(r"(?i)treat\b.*\bas\s+(minor|trivial)"),
    re.compile(r"(?i)downgrade\s+(it|this|the\s+severity)"),
]
```

**Affected files**:


**Expected tests**:



### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.

### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/home/ek/projects/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-050 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-050/impl-plan.md`
- Full spec: `.klc/tickets/KLC-050/spec.md`
- Full test-plan: `.klc/tickets/KLC-050/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-050 step-1` and
run `klc step KLC-050 2` to get the next step's card,
or `klc ack KLC-050 --pick 1` if this was the last step.
