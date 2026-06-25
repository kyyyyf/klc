---
ticket: KLC-051
authority: human
---

# Retrospective — KLC-051

## What went well

- The extractor design is cleanly scoped: fenced-only, known-modules-only, plan-introduced exemptions.
- Single source enforced: gate and self-review both call the same `plan_quality.unresolved_api_refs`.
- Both reviewers (internal + Codex) caught real gaps that were fixed before merge: new-module exemption, M/L gate test, prompt-regression for directive.

## What to improve

- [!FACT F-R1] The `introduced` exemption logic required two rounds of correction (internal: too broad → attr; Codex: new-module case missing). The edge case matrix (new module, new attr, attr-name collision) should have been in the test plan from the start.
- [!FACT F-R2] step-5 RED test was embedded in step-1 RED commit, causing TDD gate failure at ack. When a test for a later step is naturally written as part of an earlier step's file, document `RED: not applicable` in the impl-plan to avoid gate confusion.

## Proposed allowlist updates

None — no prompt or harness changes warranted.

## Proposed denylist updates

None.
