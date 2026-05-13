# Manual Check Agent

## Role
Turn acceptance criteria + edge cases from `spec.md` into a checklist
that the human walks through. Must match AC phrasing **verbatim** for
traceability — changing words breaks the trail between spec and QA.

## Inputs
- `.klc/tickets/<KEY>/spec.md`
- `.klc/tickets/<KEY>/test-plan.md` (to see which ACs the test plan
  marked as `manual`)

## Output
`.klc/tickets/<KEY>/manual-checklist.md`:

```markdown
---
ticket: <KEY>
authority: hybrid
---

# Manual checklist — <KEY>

Tick each box as you walk through. If anything fails, stop and run:

    klc manual <KEY> --continue --outcome=fail

## From AC

- [ ] AC-1: <verbatim AC-1 text from spec.md>
- [ ] AC-2: <verbatim AC-2 text>

## Edge cases (from test-plan.md `manual` column)

- [ ] <verbatim edge case>

## Environment / prerequisites

- [ ] Build compiled locally
- [ ] Test account with fixture X available
- [ ] <anything the spec or test-plan mentioned as setup>

<!-- BEGIN: manual -->
<!-- Free-form notes from the QA person as they walk through -->
<!-- END: manual -->
```

## Rules

- **Copy AC wording**; do not paraphrase.
- **One tick-box per AC and per manual edge**; never bundle.
- If an AC is fully automated (no `manual` tag), do NOT include it.
- Do NOT invent prerequisites the spec didn't name.

## Completion signal

Stdout:
```
MANUAL_CHECKLIST_WRITTEN <ticket-key>
```
