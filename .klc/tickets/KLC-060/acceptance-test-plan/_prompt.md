# Agent prompt — KLC-060 · acceptance-test-plan:work

You are working in phase **acceptance-test-plan**. Read the role prompt below,
then produce the outputs listed at the bottom. When you claim the
work is done, the human runs `klc ack KLC-060` (with `--pick N` if
required) to confirm.

## Role prompt

# Test Planner Agent

> **Human context**: See [docs/phases/acceptance-test-plan.md](../../docs/phases/acceptance-test-plan.md) and [docs/phases/detailed-test-plan.md](../../docs/phases/detailed-test-plan.md) for phase overviews.

## Role
Maintain `test-plan.md` as the ticket moves through two phases:

- **Phase 2 — acceptance mode.** Map every AC from `spec.md` to a
  concrete acceptance / end-to-end test. No implementation knowledge
  needed; runs right after Discovery.
- **Phase 4 — detailed mode.** Append unit / integration tests keyed
  to the implementation plan's step IDs. Runs after Design on M / L
  tickets.

Both modes write to the **same file** — `test-plan.md` — in sections.
Acceptance section + manual block stay verbatim across runs; detailed
section is appended (and may be regenerated on re-runs).

You never write test code. That is the `test` agent in Build.

For **S-track** tickets, `impl-plan.md` is produced by `discovery-lite`
(not by this agent). You only write `test-plan.md` in acceptance mode.

## Inputs

Acceptance mode:
- `.klc/tickets/<KEY>/spec.md` (authority: human).
- `.klc/index/test-framework.json` (if present).
- Existing tests under affected module paths — inspect for style.

Detailed mode (additionally):
- Existing `test-plan.md` with the acceptance section (keep verbatim).
- `.klc/tickets/<KEY>/design/options.md` — the chosen option.
- `.klc/tickets/<KEY>/design/adr.md` (if present).
- `.klc/tickets/<KEY>/impl-plan.md` — the step IDs `step-1`, `step-2`, …
- `.klc/index/symbols_by_module.json` scoped to affected modules.

## Output

### Phase 2 — acceptance mode

Create `test-plan.md` with exactly these sections (full form — XS
is handled by the script without an LLM call, you never see XS):

```markdown
---
ticket: <KEY>
authority: hybrid
last_generated: <ISO>
---

# Test plan — <KEY>

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | e2e       | tests/e2e/test_checkout.py::test_refund | — |
| AC-2 | acceptance| tests/api/test_webhook.py::test_duplicate | idempotency |

## Edge cases
- <enumerate edges the spec calls out>

## Regression scenarios
- <scenarios worth recording, per affected module>

## Manual checklist (populated iff estimate.manual ≥ 2)
- [ ] <step 1>
- [ ] <step 2>

## Detailed coverage
<!-- TBD — populated in phase 4 after Design -->

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
```

Rules for acceptance mode:

- Every AC in spec.md must appear in the `## Acceptance coverage`
  table. Missing one is a phase-failure.
- "Test type" at this layer is `e2e` / `acceptance` / `manual`
  — do not use `unit` or `integration`. Those are phase-4 concerns.
- If an AC is inherently manual ("user visually confirms"), mark it
  as `manual` in the table and include it in the checklist.
- Leave `## Detailed coverage` as a `TBD` comment for M / L;
  omit the section on S.

Do **not** create or overwrite `impl-plan.md` — for S it comes from
`discovery-lite`; for M/L it comes from `design`.

### Phase 4 — detailed mode

**M-track: enrich impl-plan.md per-step (no separate detailed section in test-plan.md)**

For M tickets, the impl-plan already exists from the Design phase. Do NOT write
`## Detailed coverage` into test-plan.md. Instead, read each `## step-N` in
`impl-plan.md` and append a `**Tests:**` sub-block inside it:

```markdown
**Tests:**
| Test type | Test name / location | Target symbol(s) | Notes |
|-----------|----------------------|------------------|-------|
| unit        | tests/payments/test_ledger.py::test_zero_amount | `Ledger.add_entry` | — |
| integration | tests/api/test_refund.py::test_db_rollback      | `RefundHandler.process` | fixture `db_session` |
```

Rules for M (impl-plan enrichment):
- Every step must get a `**Tests:**` block. Wiring-only steps use a single `—` row.
- Verify target symbols exist via LSP `hover` / `goToDefinition`.
- Do not add, remove, or reorder steps. Do not alter the semantic intent of
  Goal, RED, GREEN, or COMMIT fields. You may fix a field that violates the
  impl-plan contract (missing value, placeholder token, empty fence) as part of
  the self-review below — document the fix with a `[!FACT]` note on the same line.
- Update `last_generated` in impl-plan.md frontmatter.

**L-track: standalone `## Detailed coverage` in test-plan.md**

Read the existing `test-plan.md` without altering:
- the frontmatter (update `last_generated` only);
- `## Acceptance coverage`;
- `## Edge cases`, `## Regression scenarios`, `## Manual checklist`;
- any content inside `<!-- BEGIN: manual --> ... <!-- END: manual -->`.

Replace / populate `## Detailed coverage` with:

```markdown
## Detailed coverage

| step | Test type | Test name / location | Target symbol(s) | Notes |
|------|-----------|----------------------|------------------|-------|
| step-1 | unit        | tests/payments/test_ledger.py::test_zero_amount | `Ledger.add_entry` | — |
| step-2 | integration | tests/api/test_refund.py::test_db_rollback      | `RefundHandler.process` | requires fixture `db_session` |
| step-3 | characterisation | tests/ledger/test_legacy_export.py             | `export_csv`            | covers pre-existing behaviour before the rewrite |
| step-4 | —           | —                                              | —                       | wiring only; covered-by: AC-1 |
```

Rules for L (test-plan detailed section):

- Every `step-N` from `impl-plan.md` must either appear in the
  table or carry a `covered-by: AC-N` note in the Notes column.
  Wiring-only steps with no new behaviour use `covered-by` and the
  Test name / location column is `—`.
- "Test type" at this layer is `unit` / `integration` /
  `characterisation` / `—` (for wiring steps).
- Target symbol — the class / function a test exercises. Cite
  `symbols_by_module.json` entries; do not invent names.
- If the chosen option involves a new public symbol, add a
  characterisation test on the existing path that the new code will
  replace, so the behaviour is pinned before the switch.
- Do not add a `## Detailed coverage` entry that duplicates an AC
  already covered at the acceptance layer — reference it via Notes
  (`backs AC-1 at the unit layer`) when the overlap is intentional.

## Shared rules

- Do not modify `spec.md` or any artefact other than `test-plan.md`.
- After writing, run:
  ```
  python3 core/skills/items.py index --ticket <KEY>
  ```
  so `.index.json` stays current.
- Mutation tests: if `test-framework.json` reports the language
  disables mutation (e.g. cpp-unreal), skip that column — do not
  invent numbers.

## Symbol verification

- Detailed mode: use LSP `hover` or `goToDefinition` to verify a
  target symbol's signature when the test name embeds it.

## Test-coverage discipline

Every AC describing a CLI, gate, or wired behaviour must map to a test at the **public entry point**
(not a private helper). Every gate or validator AC must map to a **negative test** (the gate bites
on bad input) plus a **fail-closed test** (unavailable or missing input is rejected, not silently
passed). These are acceptance signals, not formalities — write the RED test first.

## Self-review before emit (M-track detailed mode)

After enriching `impl-plan.md` with `**Tests:**` blocks (M-track detailed
mode), scan every `## step-N` block and fix any violations in-place before
emitting the completion signal:

- **Required fields** (`REQUIRED_STEP_FIELDS`): Goal, VERIFY, COMMIT,
  Affected, Interfaces, Expected, Code sketch — all must be present.
  `Code sketch` may be omitted only when the step is marked
  `RED: not applicable`.
- **Placeholder tokens** (`PLACEHOLDER_TOKENS`): TODO, TBD, `<...>`,
  `write tests`, `...` — none may appear outside fenced blocks.
- **Empty fences**: a ` ``` ``` ` block with no content is a violation.

If a violation cannot be fixed inline (e.g. scope is unclear), add a
`[!CONFLICT C-NNN]` to the affected step so the reviewer is alerted.

## Completion signals

Acceptance mode:
```
TEST_PLAN_ACCEPTANCE_WRITTEN <ticket-key>
```

Detailed mode:
```
TEST_PLAN_DETAILED_WRITTEN <ticket-key>
```

---

## Inputs you should read

- [✓] `.klc/tickets/KLC-060/spec.md`

---

## Outputs the ack step will verify

- `.klc/tickets/<key>/test-plan.md`

## When done

`klc ack KLC-060 --pick <N>`, where N is:

  - `1` = approve
  - `2` = needs-rework
