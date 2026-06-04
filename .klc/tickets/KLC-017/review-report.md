---
ticket: KLC-017
phase: review
authority: agent
verdict: APPROVED
---

# KLC-017 review report

## Summary

APPROVED. Zero blocking issues. Three non-blocking findings.

ISSUES_TOTAL=3 ISSUES_BLOCKING=0

---

## Security

No issues. `KLC_CARD_INLINE` env-var is read-only, not interpolated into
commands. `impl_prompt_ref` is a local filesystem path rendered into a
markdown file, not executed. No new secrets, HTTP calls, or shell
invocations introduced.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

---

## Architecture

### [MEDIUM] Dead kwargs in `_PREAMBLE_TMPL.format()` call

**File**: `core/skills/artefacts.py:183`

`write_prompt_card()` still passes `track=track, kind=kind` into
`.format()` after the `{track}` and `{kind}` placeholders were removed
from `_PREAMBLE_TMPL`. Python silently ignores extra kwargs — no crash —
but these arguments are now dead code in the call site.

Not blocking; the card renders correctly. Clean up in a follow-up or
opportunistically.

ISSUES_TOTAL=1 ISSUES_BLOCKING=0

---

## Performance

No blocking issues. The compressed-card path delivers the intended
~7.2 KB saving per build step. No new N+1 reads or hot-path
regressions introduced.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

---

## Test coverage

### [LOW] No assertion on `write_prompt_card` output after preamble trim

`_PREAMBLE_TMPL` no longer contains `{track}` / `{kind}`. Smoke and e2e
pass, but there is no test that explicitly asserts the preamble still
renders a usable card for non-build phases (e.g. discovery). The
regression risk is low but the gap exists.

### [LOW] `source_counts` rollup not covered by an executable test

`test_rollup_source_counts` was written but excluded from the `__main__`
block due to mocking complexity. The rollup `source_counts` field is
therefore not verified by any test that actually runs.

ISSUES_TOTAL=2 ISSUES_BLOCKING=0

---

## Verdict

**APPROVED** — zero blocking issues. The three non-blocking findings
(dead kwargs, missing preamble test, untested rollup path) are
improvements for a follow-up, not blockers for this ticket.
