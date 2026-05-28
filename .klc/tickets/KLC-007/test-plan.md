---
ticket: KLC-007
authority: hybrid
last_generated: 2026-05-28T14:10:00Z
---

# Test plan — KLC-007

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/audit/test_file_coverage.py::test_all_53_files_listed | Verify audit table in spec.md lists all 53 files (35 core/skills + 13 core/phases + 5 scripts) with disposition field |
| AC-2 | acceptance | tests/audit/test_duplicate_patterns.py::test_duplicate_logic_documented | Verify spec.md identifies duplicate logic patterns (YAML, paths, artefact I/O) |
| AC-3 | acceptance | tests/audit/test_bak_files.py::test_bak_files_listed | Verify spec.md lists all .bak files for deletion |
| AC-4 | acceptance | tests/audit/test_shared_helpers.py::test_extractable_helpers_documented | Verify spec.md documents shared helpers worth extracting |
| AC-5 | acceptance | tests/audit/test_loc_estimate.py::test_loc_reduction_calculated | Verify spec.md includes LOC reduction estimate with calculation |
| AC-6 | manual | Build phase: Verify .bak files removed | Deferred to build phase (post-KLC-006) |
| AC-7 | manual | Build phase: Verify skill CLIs standardized | Deferred to build phase (post-KLC-006) |
| AC-8 | acceptance | Build phase: tests/smoke.py passes | Deferred to build phase (post-KLC-006) |
| AC-9 | acceptance | Build phase: LOC reduction ≥10% | Deferred to build phase (post-KLC-006) |

## Edge cases

- **File count mismatch**: If filesystem has different file count than 53, test should fail with actual count vs expected.
- **Missing disposition**: If any file in audit table lacks disposition field, test should fail listing incomplete entries.
- **Hidden .bak files**: Audit must check for .bak files in subdirectories, not just top-level.
- **LOC calculation accuracy**: Reduction estimate should be based on actual file sizes (wc -l), not guessed.

## Regression scenarios

- **Affected module `core/skills`**: After refactor, ensure all skills still callable (CLI entry points functional).
- **Affected module `core/phases`**: After refactor, ensure phase state machine still works (all transitions valid).
- **Affected module `scripts`**: After refactor, ensure `klc` CLI still functional (status, ack, step commands).
- **Cross-module imports**: After merge/move operations, ensure no broken imports (grep for old paths).

## Manual checklist

- [ ] Review audit table completeness (all 53 files covered)
- [ ] Verify duplicate patterns are actionable (specific file references, not vague)
- [ ] Confirm .bak files safe to delete (no critical content)
- [ ] Validate LOC reduction estimate methodology (actual counts, not estimates)

## Detailed coverage

| step | Test type | Test name / location | Target symbol(s) | Notes |
|------|-----------|----------------------|------------------|-------|
| step-1 | unit | tests/shared/test_module_import.py::test_import_shared | `core.shared` module | Verifies module loads |
| step-2 | unit | tests/shared/test_yaml.py::test_load_yaml | `core.shared.yaml.load_yaml` | YAML loading |
| step-2 | unit | tests/shared/test_yaml.py::test_load_with_defaults | `core.shared.yaml.load_with_defaults` | Default merging |
| step-2 | unit | tests/shared/test_yaml.py::test_validate_schema | `core.shared.yaml.validate_schema` | Schema validation |
| step-3 | unit | tests/shared/test_paths.py::test_resolve_path | `core.shared.paths.resolve` | Path resolution |
| step-3 | unit | tests/shared/test_paths.py::test_normalize_path | `core.shared.paths.normalize` | Path normalization |
| step-4 | unit | tests/shared/test_artefacts.py::test_write_with_frontmatter | `core.shared.artefacts.write_with_frontmatter` | Artefact writing |
| step-4 | unit | tests/shared/test_artefacts.py::test_lock_artefact | `core.shared.artefacts.lock` | Artefact locking |
| step-5 | — | — | — | covered-by: step-2,3,4 tests |
| step-6 | integration | tests/smoke.py | All skills | Regression check |
| step-7 | — | — | — | Analysis step, no test |
| step-8 | integration | tests/skills/test_batch1_imports.py | Skills 1-10 | Import validation |
| step-9 | integration | tests/skills/test_batch2_imports.py | Skills 11-20 | Import validation |
| step-10 | integration | tests/skills/test_batch3_imports.py | Skills 21+ | Import validation |
| step-11 | e2e | tests/e2e_pipeline.py | Full lifecycle | 4 tracks (XS/S/M/L) |
| step-12 | characterisation | tests/skills/test_no_serena_imports.py | grep "serena" | Verify no serena imports remain |
| step-13 | unit | tests/audit/test_no_bak_files.py | `find . -name "*.bak"` | Verify .bak files gone |
| step-14 | unit | tests/skills/test_phase_completion.py::test_validator_functions | `phase_completion.validate_spec` | Moved from validator |
| step-15 | unit | tests/shared/test_yaml.py::test_merge_yaml | `core.shared.yaml.merge` | Merged from yaml_merge |
| step-16 | integration | tests/skills/test_merged_imports.py | validator, yaml_merge users | Import updates work |
| step-17 | unit | tests/index/test_modules_json.py::test_core_shared_present | `.klc/index/modules.json` | Index has core.shared |
| step-18 | acceptance | tests/audit/test_loc_reduction.py::test_loc_reduction_target | wc -l analysis | ≥10% reduction (backs AC-9) |

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
