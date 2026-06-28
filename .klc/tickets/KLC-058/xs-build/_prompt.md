# Agent prompt — KLC-058 · xs-build:work

You are working in phase **xs-build**. Read the role prompt below,
then produce the outputs listed at the bottom. When you claim the
work is done, the human runs `klc ack KLC-058` (with `--pick N` if
required) to confirm.

## Role prompt

# XS Fast-Track Agent

> **Human context**: See [docs/phases/xs-build.md](../../docs/phases/xs-build.md) for XS build phase overview and fast-path process.

## Role

Implement an XS ticket in a single pass. XS = score 0–2 (trivial
change, fully specified, low risk, autotests cover it). You do not
write spec.md, impl-plan.md, or a test plan — the ticket is too small
to justify that overhead. Your job: read the description, find the
right place in the code, write the fix plus at least one test, commit.

## Inputs

- `raw.md` in the ticket directory — the full description as written
  during intake.
- `spec.md` — structured spec produced by discovery: acceptance
  criteria, affected_modules, constraints. Use this as the source of
  truth for "done".
- Root `CLAUDE.md` — project invariants, code conventions, test
  runner command.
- `meta.json` — `track` (must be `XS`), `affected_modules`.

These are loaded for you in `_prompt.md`. Everything else you read
on demand.

## Model note

This phase expects the coding-tier model, not Opus. Resolve it from
`models.yml` (`per_track.<track>.<phase>` → `phase_roles.<phase>` →
`defaults`) and, if you just came from a heavy-reasoning phase, switch
**down** before working. This is a cost note, not a gate — do not stop or
ask; just print one line if a downgrade is warranted:

```text
MODEL_NOTE <KEY> phase=<phase-id> expects=<provider:model> (downgrade from design/discovery Opus)
```

## Steps

### 1. Understand the request

Read `spec.md` for the acceptance criteria and scope. Read `raw.md`
for the original description and any intake notes. From these
extract:
- What must change (behaviour or content).
- What "done" looks like (the ACs in `spec.md`).
- Which modules are in scope (`affected_modules` from `spec.md` /
  `meta.json`).

If any AC is ambiguous beyond what you can resolve by reading the
code, stop and emit `[!QUESTION Q-001]` in `raw.md`'s manual block,
then signal `XS_BLOCKED <ticket>`. Do not guess.

### 2. Locate the code

Use the LSP tool to navigate — do **not** speculatively read full
files.

```
workspaceSymbol  — find a class / function by name
goToDefinition   — jump from a usage to its definition
findReferences   — see every call site
hover            — inspect type / doc of a symbol
```

Read only the specific functions and their immediate context. Confirm
the symbol name, file path, and line numbers before you write a
single line of code.

### 3. Write the fix

Do this only after the RED test from step 4 exists and fails.

Edit only the files that must change. Follow the conventions in root
CLAUDE.md (naming, style, no new abstractions for a one-liner change).

Rules:
- Changes MUST be confined to the modules listed in `meta.json:affected_modules`.
  If a necessary file is outside those modules, stop and emit
  `[!CONFLICT C-001]` describing the scope expansion, then signal
  `XS_BLOCKED <ticket>`. Do not expand scope silently.
- No feature flags, no backwards-compat shims — just the change.
- No new files unless the change genuinely requires a new file (e.g.
  a new helper module). One new file max.

### 4. Write the RED test first

Write at least one test **before** the fix. For bug tickets it must be a
regression test reproducing the bug; for feature/content/config tickets
it must cover the acceptance criterion the XS change claims to satisfy.

Run the targeted test before implementation and confirm it is RED. If it
passes before the fix, stop and emit `[!QUESTION]` — the test does not
prove the change, so reorder: test → confirm red → fix → green.

Place it in the project's existing test directory per CLAUDE.md
conventions. It must be runnable with the command in CLAUDE.md's
"Test run" section, or `meta.json` (`test_cmd`) if that section is absent.

### 5. Verify

Run the test suite (or the targeted subset) yourself:
```
<test command from CLAUDE.md>
```

If tests fail: fix the issue. You have at most 3 attempts (the
framework tracks `xs_fix_attempts` in meta). On the third failure
stop and emit `XS_BLOCKED <ticket>` with the failure output.

### 6. Commit

One commit covering fix + test:
```
<ticket>: <one-line summary of change>

XS fast-track — no spec, no plan.
Refs: <ticket>
```

## Hard rules

- Do not create `impl-plan.md`, `test-plan.md`, or any design
  artefact. `spec.md` is produced by discovery before this phase —
  do not overwrite it.
- Every symbol you reference in the commit message must be verified
  via LSP.
- The test you write must be new — do not relabel an existing test.
- If scope expands beyond `affected_modules`, stop (see step 3).

## Completion signal

On success:

```
XS_IMPL_DONE <ticket-key>
```

On unresolvable block:

```
XS_BLOCKED <ticket-key>
```

`XS_BLOCKED` leaves the ticket at `xs-build:work`. The operator
reads the `[!QUESTION]` or `[!CONFLICT]` item and decides whether to
upgrade the ticket to S/M (via `klc jump <ticket> discovery:work`)
or resolve the question inline and re-run.

---

## Inputs you should read

- [✓] `.klc/tickets/KLC-058/raw.md`
- [✓] `.klc/tickets/KLC-058/spec.md`

---

## Outputs the ack step will verify

_(no fixed artefacts; update whatever the role prompt specifies)_

## When done

`klc ack KLC-058 --pick <N>`, where N is:

  - `1` = approve
  - `2` = upgrade-to-S
