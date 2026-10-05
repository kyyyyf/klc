## Assess the independent review findings for your step (before any code)

Three independent planning-layer reviewers record OBJECTIVE findings before
build: spec-review, test-plan-review and impl-plan-review. They record into
the ticket's one `findings.json`, each record tagged with its `kind`
(`spec-review`, `test-plan-review`, `impl-plan-review`) and its `round`. All
share one schema, `findings.Finding`
(`kind · round · rule_name · severity · file · line · title · body · fix`,
`severity ∈ CRITICAL|HIGH|MEDIUM|LOW|INFO`).

Your brief has a `## Review findings for this step` section that lists the
findings relevant to this step. Do not read the findings files yourself;
assess the findings listed in the brief, before coding the step:

1. For EACH listed finding, record an assessment in `build-log.md` (free notes) — **fix**
   (the defect is real; note how the build accounts for it, or raise a
   `[!CONFLICT]`/`[!DECISION]`) or **won't-fix** (with a one-line reason).
2. A `HIGH` (or `CRITICAL`) finding that is neither fixed nor consciously
   waived is a stop-and-ask: raise a `[!QUESTION]` / `[!CONFLICT]` rather
   than building past it.
3. `(none)` — or an absent findings file — means nothing to assess; proceed.
   Do not fabricate findings.
