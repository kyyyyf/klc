---
ticket: KLC-007
authority: agent
generated: 2026-05-28T14:05:00Z
based_on: design/adr.md (Option B)
---

# Implementation Plan — KLC-007

## Overview

Refactor code per Option B (clean architecture): extract shared helpers to `core/shared/`, migrate imports, delete dead files. Three-phase rollout for safety.

## Prerequisites

- [ ] KLC-006 (documentation) archived ✓
- [ ] Feature branch created from main ✓
- [ ] tests/smoke.py baseline passes

## Implementation steps

### Phase 1: Create `core/shared/` module

- [ ] **step-1**: Create `core/shared/` module structure
  - **Affected files**: `core/shared/__init__.py` (new)
  - **Description**: Create module directory and init file
  - **Expected tests**: tests/shared/test_module_import.py (import validation)

- [ ] **step-2**: Extract YAML utilities to `core/shared/yaml.py`
  - **Affected files**: `core/shared/yaml.py` (new), `core/skills/_yaml.py` (reference)
  - **Description**: Extract `load_yaml()`, `load_with_defaults()`, `validate_schema()` from _yaml.py and 5 duplicating files
  - **Expected tests**: tests/shared/test_yaml.py (load, defaults, schema validation)
  - **Sources**: Analyze `core/skills/_yaml.py` + grep for duplicate YAML loaders

- [ ] **step-3**: Extract path utilities to `core/shared/paths.py`
  - **Affected files**: `core/shared/paths.py` (new), `core/skills/_paths.py` (reference)
  - **Description**: Extract common path resolution patterns from 8 files
  - **Expected tests**: tests/shared/test_paths.py (resolve, normalize, exists checks)
  - **Sources**: Analyze `core/skills/_paths.py` + grep for path resolution patterns

- [ ] **step-4**: Extract artefact utilities to `core/shared/artefacts.py`
  - **Affected files**: `core/shared/artefacts.py` (new), `core/skills/artefacts.py` (reference)
  - **Description**: Extract write-with-frontmatter, lock, prompt generation from 12 files
  - **Expected tests**: tests/shared/test_artefacts.py (write, lock, frontmatter parsing)
  - **Sources**: Analyze `core/skills/artefacts.py` + grep for duplicate artefact writes

- [ ] **step-5**: Add unit tests for `core/shared/` module
  - **Affected files**: `tests/shared/test_yaml.py`, `tests/shared/test_paths.py`, `tests/shared/artefacts.py` (new)
  - **Description**: Comprehensive unit tests for all extracted utilities
  - **Expected tests**: 15-20 test cases covering edge cases
  - **Coverage target**: ≥90% for core/shared/

- [ ] **step-6**: Run smoke tests + commit Phase 1
  - **Affected files**: None (validation step)
  - **Description**: Verify `tests/smoke.py` still passes, commit PR #1
  - **Expected tests**: tests/smoke.py (14 blocks pass)

### Phase 2: Migrate imports to `core/shared/`

- [ ] **step-7**: Identify all files importing old utilities
  - **Affected files**: None (analysis step)
  - **Description**: Grep for imports from `core.skills._yaml`, `core.skills._paths`, `core.skills.artefacts`
  - **Expected output**: List of 20-30 files to update

- [ ] **step-8**: Update imports batch 1 (skills 1-10)
  - **Affected files**: 10 files in `core/skills/` (first batch)
  - **Description**: Replace old imports with `from core.shared import yaml, paths, artefacts`
  - **Expected tests**: Smoke tests for these 10 skills

- [ ] **step-9**: Update imports batch 2 (skills 11-20)
  - **Affected files**: 10 files in `core/skills/` (second batch)
  - **Description**: Continue import migration
  - **Expected tests**: Smoke tests for these 10 skills

- [ ] **step-10**: Update imports batch 3 (remaining skills + phases)
  - **Affected files**: 10+ files in `core/skills/`, `core/phases/` (final batch)
  - **Description**: Complete import migration
  - **Expected tests**: Full smoke suite

- [ ] **step-11**: Run E2E tests + commit Phase 2
  - **Affected files**: None (validation step)
  - **Description**: Verify `python tests/e2e_pipeline.py` passes all tracks
  - **Expected tests**: E2E (XS/S/M/L all green)

### Phase 3: Delete dead files, merge duplicates

- [ ] **step-12**: Delete serena files
  - **Affected files**: `core/skills/serena.py` (delete), `core/skills/serena-call-graph.py` (delete)
  - **Description**: Remove legacy orchestrator (535 LOC)
  - **Expected tests**: Grep for remaining imports (should be 0)

- [ ] **step-13**: Delete .bak files
  - **Affected files**: `core/skills/callgraph_rust_pattern.py.bak` (delete)
  - **Description**: Remove backup files
  - **Expected tests**: `find . -name "*.bak"` returns empty

- [ ] **step-14**: Merge validator.py into phase_completion.py
  - **Affected files**: `core/skills/validator.py` (delete), `core/skills/phase_completion.py` (extend)
  - **Description**: Move spec validation functions to phase_completion
  - **Expected tests**: tests/skills/test_phase_completion.py (validator functions work)

- [ ] **step-15**: Merge yaml_merge.py into _yaml.py or deprecate
  - **Affected files**: `core/skills/yaml_merge.py` (delete), `core/skills/_yaml.py` or `core/shared/yaml.py` (extend)
  - **Description**: Consolidate YAML merge logic (may be redundant with core/shared/yaml)
  - **Expected tests**: tests/shared/test_yaml.py (merge logic)

- [ ] **step-16**: Update imports for merged files
  - **Affected files**: 5-10 files importing validator, yaml_merge
  - **Description**: Fix import paths after merges
  - **Expected tests**: Smoke tests

- [ ] **step-17**: Rebuild module index
  - **Affected files**: `.klc/index/modules.json`, `.klc/index/symbols_by_module.json`
  - **Description**: Run `scripts/init.py` to regenerate index with new structure
  - **Expected tests**: Index contains `core.shared` module

- [ ] **step-18**: Final validation + commit Phase 3
  - **Affected files**: None (validation step)
  - **Description**: Run smoke + E2E tests, verify LOC reduction ≥10%
  - **Expected tests**: tests/smoke.py + E2E + LOC count

## Validation gates

After each phase:
- [ ] `tests/smoke.py` passes (14 blocks)
- [ ] No import errors in `klc status`, `klc ack`, `klc step`
- [ ] Git diff shows expected files changed (no accidental edits)

After Phase 3 (final):
- [ ] `python tests/e2e_pipeline.py` passes (all 4 tracks)
- [ ] LOC reduction ≥10% (target: 700-800 LOC removed)
- [ ] Module index reflects new structure (`.klc/index/modules.json` has `core.shared`)

## Rollback plan

- **Phase 1 failure**: Delete `core/shared/`, abandon refactor → revert to Option A
- **Phase 2 failure**: Revert import updates, keep `core/shared/` (unused)
- **Phase 3 failure**: Restore deleted files from git, fix imports

## Estimated effort

- **Phase 1**: 8-10 hours (create shared module + tests)
- **Phase 2**: 8-10 hours (migrate 20-30 imports)
- **Phase 3**: 6-8 hours (delete + merge + index rebuild)
- **Total**: 22-28 hours (within ADR estimate of 24-32h)

## Dependencies

- **Blocks**: None (can proceed immediately)
- **Blocked by**: KLC-006 ✓ (already archived)
- **Unblocks**: KLC-009 (config cleanup) after this completes

<!-- BEGIN: manual -->
<!-- Human adjustments to plan -->
<!-- END: manual -->
