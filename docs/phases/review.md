# Review phase (S/M/L)

## Purpose
Audit implementation against spec/ADR. Check correctness, completeness, quality, security.

## Inputs
- Code changes from build
- `spec.md`
- `test-plan.md`
- `design/adr.md` (M/L only)
- `impl-plan.md` (M/L only)
- `build-log.md`

## Outputs
- `review-report.md` — findings and verdict

## Process
Reviewer (human or agent) audits:
- **Scope**: Stayed within affected_modules?
- **Correctness**: Matches spec/ADR?
- **Completeness**: All ACs covered by tests?
- **Quality**: Code style, test coverage, docs
- **Security**: OWASP top 10 checks

## Completion criteria
- review-report.md exists with verdict
- All critical findings resolved (or accepted)

## Ack options
- `--pick 1` (approve): Advance based on track
  - S → integrate:work
  - M/L → manual:work
- `--pick 2` (needs-rework): Back to build:work
- `--pick 3` (escalate): Human decision needed

## Common pitfalls
- Scope creep not caught (files outside affected_modules)
- Missing AC coverage (no test for AC-N)
- Security vulnerability missed (SQL injection, XSS, etc.)

## Example
S ticket: Review clean → approve → integrate:work  
M ticket: Review finds scope issue → needs-rework → build:work
