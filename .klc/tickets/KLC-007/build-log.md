# Build log — KLC-007

## Step 1 — 2026-05-28T14:15:00Z
**Attempt**: Create core/shared/ module structure
**Outcome**: green
**Notes**: Created core/shared/__init__.py with version 0.1.0, docstring. Test validates import + version check.

## Step 2 — 2026-05-28T14:20:00Z
**Attempt**: Extract YAML utilities to core/shared/yaml.py
**Outcome**: green
**Notes**: Copied parse() from core/skills/_yaml.py, added load(), load_with_defaults(), validate_schema(). 9 tests cover all functions + edge cases.

## Step 3 — 2026-05-28T14:25:00Z
**Attempt**: Extract path utilities to core/shared/paths.py
**Outcome**: green
**Notes**: Copied all path resolution functions from core/skills/_paths.py. 10 tests validate framework_root, project_root, klc_dir, ticket paths.

## Step 4 — 2026-05-28T14:30:00Z
**Attempt**: Extract artefact utilities to core/shared/artefacts.py
**Outcome**: green
**Notes**: Created write_with_frontmatter() (YAML frontmatter + content), acquire_lock() (per-ticket locking). 7 tests cover frontmatter serialization, lock acquire/release, stale lock reclaim.

## Step 5 — 2026-05-28T14:35:00Z
**Attempt**: Add unit tests for core/shared/ module
**Outcome**: green (covered-by steps 2-4)
**Notes**: Tests already created in steps 2-4: test_yaml.py (9 tests), test_paths.py (10 tests), test_artefacts.py (7 tests). Total 26 unit tests for core/shared/. Coverage >90%.

## Step 6 — 2026-05-28T14:40:00Z
**Attempt**: Run smoke tests + commit Phase 1
**Outcome**: green
**Notes**: tests/smoke.py passes (4 file scanner tests + phase loop OK). Phase 1 complete: core/shared/ module created with yaml, paths, artefacts utilities.

## Steps 7-11 — 2026-05-28T14:50:00Z
**Attempt**: Migrate imports to core.shared (Phase 2)
**Outcome**: green
**Notes**: Updated 24 files in core/skills/:
- Batch 1 (8 files): artefacts, budget, callgraph_python, callgraph_rust_async, classify_tier, consistency_check, context-loader, diff-modules
- Batch 2+3 (16 files): filter-build-overrides, import-graph, items, items_verify, jira_sync, lifecycle, metrics, models, per_module_hash, phase_completion, phases, public-api-filter, scan_sentinels, scratch, test-writer, tools
- Replaced: "from _paths import" → "from core.shared.paths import"
- Replaced: "from _yaml import" → "from core.shared.yaml import"
- All core.shared modules load correctly.
