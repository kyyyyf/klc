---
ticket: KLC-009
authority: hybrid
last_generated: 2026-05-28T14:27:00Z
---

# Test plan — KLC-009

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | manual | spec.md audit table | Verify audit table completeness in spec.md |
| AC-2 | manual | git show HEAD | Verify commit message explains removed keys |
| AC-3 | acceptance | tests/e2e_pipeline.py::test_config_headers | Parse each config file, verify header comment exists |
| AC-4 | acceptance | tests/e2e_pipeline.py::test_severity_rubric_location | Assert docs/severity-rubric.md exists, config/severity-rubric.md does not |
| AC-5 | acceptance | tests/e2e_pipeline.py::test_doctor_unknown_keys | Add unknown key to config/tiers.yml, run klc doctor, assert warning |
| AC-6 | e2e | tests/smoke.py + tests/e2e_pipeline.py | Full regression suite |
| AC-7 | manual | Line count check | wc -l config/*.{yml,yaml,md}, verify ≤870 lines total |

## Edge cases
- Empty/malformed YAML files should be detected by validate_config.py (AC-5)
- Config files with valid YAML but unknown keys should trigger warnings, not errors
- Seed files (reviewer-allowlist.seed.yml) should not be validated at runtime
- Moving severity-rubric.md should not break any existing documentation links

## Regression scenarios
- **core/skills/** — All config-loading skills must continue to load configs successfully
  - phases.py must load phases.yml without errors
  - models.py must load models.yml without errors
  - classify_tier.py must load tiers.yml with standardized naming
  - scan_sentinels.py must load sentinels.yml with standardized naming
  - review.py must load reviewers.yml without errors
  - jira_sync.py must load jira.yml without errors
- **config/** — All config files remain parseable and semantically valid after cleanup
- **scripts/klc** — All klc commands continue to work (intake, discovery, ack, status, etc.)

## Manual checklist
- [ ] Review git diff to confirm only intended files changed
- [ ] Verify all config file headers accurately name their consumers
- [ ] Run `wc -l config/*.{yml,yaml,md}` and confirm ≤870 lines (15% reduction from 1022)
- [ ] Check docs/severity-rubric.md is accessible and correctly formatted
- [ ] Run `klc doctor` on a test project and verify it catches unknown config keys
- [ ] Verify config/README.md provides clear index of all config files

## Detailed coverage

| step | Test type | Test name / location | Target symbol(s) | Notes |
|------|-----------|----------------------|------------------|-------|
| step-1 | acceptance | — | — | covered-by: AC-4 |
| step-2 | acceptance | — | — | covered-by: AC-3 |
| step-3 | unit | tests/config/test_naming.py::test_snake_case_tiers | `config/tiers.yml` | Verify all keys are snake_case |
| step-3 | unit | tests/config/test_naming.py::test_snake_case_sentinels | `config/sentinels.yml` | Verify all keys are snake_case |
| step-4 | unit | tests/skills/test_validate_config.py::test_known_keys | `validate_config.validate_file` | Verify known keys pass validation |
| step-4 | unit | tests/skills/test_validate_config.py::test_unknown_keys_warning | `validate_config.validate_file` | Verify unknown keys trigger warnings |
| step-4 | unit | tests/skills/test_validate_config.py::test_skip_seed_files | `validate_config.validate_file` | Verify seed files are skipped |
| step-5 | integration | tests/e2e_pipeline.py::test_doctor_config_validation | `doctor.run` | Verify klc doctor calls validate_config |
| step-5 | acceptance | — | — | covered-by: AC-5 |
| step-6 | manual | — | — | README is documentation, manual verification sufficient |

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
