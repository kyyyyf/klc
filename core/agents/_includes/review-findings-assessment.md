## Assess the independent review findings (before any code)

Three independent planning-layer reviewers may have recorded OBJECTIVE
`findings[]` to the ticket directory before build. All three share ONE
identical schema (`id · category · severity · detail · ref · suggested_fix`,
`severity ∈ high|medium|low`), so assess them with the SAME logic — there is
no second parser and no different discipline for the three files.

| Reviewer | Findings file | Recorded at | `category` values |
|---|---|---|---|
| spec-review (KLC-084) | `spec-review-findings.json` | spec phase | free-form |
| test-plan-review (KLC-085) | `test-plan-review-findings.json` | acceptance-test-plan phase | `uncovered-ac` / `weak-assertion` / `missing-edge-case` |
| impl-plan-review (KLC-094) | `impl-plan-review-findings.json` | the ack that finalized `impl-plan.md` | `missing-step` / `wrong-sequencing` / `untestable-step` / `unaddressed-ac` / `infeasible-red-green` |

At the START of build, before writing any code, for each file that exists:

1. Read it. Each entry has `id · category · severity · detail · ref · suggested_fix`.
2. For EACH finding, record an assessment in `build-log.md` — **fix** (the
   defect is real; note how the build accounts for it, or raise a
   `[!CONFLICT]`/`[!DECISION]` as appropriate) or **won't-fix** (with a
   one-line reason). This mirrors the review-report assessment of the code
   reviewer's findings.
3. A `high`-severity finding that is neither fixed nor consciously waived is a
   stop-and-ask: raise a `[!QUESTION]` / `[!CONFLICT]` rather than building
   past it.
4. Absent file → nothing to assess (the reviewer did not run for this track,
   or its output degraded, or the phase skips it on this track); proceed. Do
   not fabricate findings.

Record all three assessment blocks under the current build-log step so
retrospective can see the spec-review, test-plan-review AND impl-plan-review
findings were handled, not dropped.
