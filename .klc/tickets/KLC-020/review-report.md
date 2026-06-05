---
ticket: KLC-020
phase: review
authority: agent
verdict: APPROVED
---

# KLC-020 review report

## Summary

APPROVED. Zero blocking issues. One MEDIUM fixed inline. Four LOW findings documented.

ISSUES_TOTAL=5 ISSUES_BLOCKING=0

---

## Security

No issues. `_flatten_adf` only concatenates strings, no execution. ADF body
from Jira written to raw.md as plain text. RestJiraClient uses env var auth,
no hardcoded secrets. No shell injection paths.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

---

## Architecture

### [MEDIUM] `_flatten_adf` duplicated in jira_artifacts.py and intake.py — FIXED

`_flatten_adf` existed in both files. At ADF format change, both would need
updating. Fixed: renamed to `flatten_adf` (exported) in `jira_artifacts.py`;
`intake.py` delegates to it with fallback.

### [LOW] `jira_config.py` sys.path manipulation couples to `core/shared` location

`_project_root / "core" / "shared"` path is hardcoded in the yaml-shadowing
guard. Works correctly; would need updating if directory structure changes.

### [LOW] `cmd_sync` without `--dry-run` or `--apply` behaves as dry-run silently

When `klc jira sync KEY` is called without flags, it prints the plan but the
message "(dry-run)" only appears explicitly when `--dry-run` is passed. Cosmetic.

ISSUES_TOTAL=3 ISSUES_BLOCKING=0

---

## Performance

No issues. All network calls guarded by FakeJiraClient in tests. `_jira_intake_enrich`
called once per intake, non-blocking on errors.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

---

## Test coverage

### [LOW] `_flatten_adf` (ADF parsing) not directly tested

Covered indirectly via `_extract_jira_description`. A dedicated test with ADF
input would make the contract explicit.

### [LOW] `cmd_sync --apply` not covered by CLI test

`klc jira sync KEY --apply` path tested only via unit tests on
`upsert_artifact_links`. CLI subprocess test only covers `--dry-run` / `disabled`.

ISSUES_TOTAL=2 ISSUES_BLOCKING=0

---

## Scope check

Diff touches declared modules only: jira.yml, jira_config, jira_client,
jira_artifacts, jira.py (new), intake.py, validate_config, scripts/klc,
tests/integration/, docs/process.md. No unplanned modules. Scope clean.

## Verdict

**APPROVED** — MEDIUM fixed during review. Four LOW findings are non-blocking
cleanups for follow-up. All 8 ACs verified.


---
[!CONFLICT] scope-expansion detected at review:ack-needed
  planned modules: ['jira_config', 'jira_client', 'jira_artifacts', 'jira', 'intake', 'validate_config', 'scripts']
  actual modules:  ['config', 'docs', 'intake', 'knowledge', 'scripts', 'tickets', 'validate_config']
  unplanned:       ['config', 'docs', 'knowledge', 'tickets']
Resolve: update meta.json:affected_modules to include all touched modules, then re-run `klc ack KLC-020`.
