---
ticket: KLC-007
authority: hybrid
last_generated: 2026-05-28T13:45:00Z
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
<!-- TBD — populated in phase 4 after Design -->

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
