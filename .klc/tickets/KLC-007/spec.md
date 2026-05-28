---
ticket: KLC-007
kind: tech
authority: agent
classification:
  complexity: 3
  uncertainty: 2
  risk: 1
  manual: 1
  total: 7
track: M
estimate_days: 7
layer: code
affected_modules:
  - core/skills
  - core/phases
  - scripts
---

# KLC-007 — Code refactoring: audit phase only

## Goals

Create comprehensive audit table of all files in `core/skills/`, `core/phases/`, `scripts/` to guide future refactoring. Mark each file: keep, merge, delete, or move.

**NOTE**: This ticket covers **discovery phase only**. Build phase (actual refactoring) will be done after KLC-006 completes.

## Problem / Context

Over Phases 1-4, code accumulated in:
- `core/skills/` — 35 Python files
- `core/phases/` — 13 Python files  
- `scripts/` — 5 Python files

Suspected issues:
1. Duplicate helper logic (YAML, paths, artefact I/O)
2. `.bak` files in tree
3. Inconsistent CLI conventions
4. Mixed responsibilities in lifecycle/phases/runner
5. Token inefficiency in build phase

## Acceptance Criteria

**For discovery phase:**
- **AC-1**: Audit table lists all 53 files with disposition (keep/merge/delete/move)
- **AC-2**: Identify duplicate logic patterns
- **AC-3**: List `.bak` files for deletion
- **AC-4**: Document shared helpers worth extracting
- **AC-5**: Estimate LOC reduction potential

**Build phase AC (deferred to post-KLC-006):**
- AC-6: `.bak` files removed
- AC-7: Skill CLIs standardized
- AC-8: `tests/smoke.py` passes
- AC-9: LOC reduction ≥10%

## Audit Table

### core/skills/ (35 files)

| File | LOC | Purpose | Disposition | Notes |
|------|-----|---------|-------------|-------|
| `_paths.py` | 120 | Path resolution utilities | **KEEP, EXPAND** | Core utility, add more helpers |
| `_yaml.py` | 45 | YAML loading wrapper | **KEEP** | Used by many skills |
| `artefacts.py` | 180 | Artefact write/lock/prompt | **KEEP** | Core infrastructure |
| `budget.py` | 135 | Cycle-limit counter | **KEEP** | Clean implementation |
| `callgraph_python.py` | 420 | Python AST call graph | **KEEP** | Feature complete |
| `callgraph_rust_async.py` | 380 | Rust LSP call graph | **KEEP** | Recently added (KLC-001) |
| `classify_tier.py` | 95 | Ticket classification | **KEEP** | Used by intake |
| `consistency_check.py` | 210 | Multi-rule validator | **KEEP** | Profile-driven |
| `context-loader.py` | 340 | ADR/spec context bundler | **KEEP** | Build phase critical |
| `dep_graph.py` | 290 | Import graph builder | **KEEP** | Index infrastructure |
| `diff-modules.py` | 85 | Affected modules from diff | **KEEP** | Review phase |
| `fact_verify.py` | 175 | Spec fact checker | **KEEP** | Discovery phase |
| `file_scanner.py` | 240 | Structural JSON builder | **KEEP** | Index foundation |
| `filter-build-overrides.py` | 65 | Build context filter | **KEEP** | Build phase |
| `filter-diff.py` | 110 | Diff patch filter | **KEEP** | Review phase |
| `findings.py` | 145 | Review findings formatter | **KEEP** | Review orchestration |
| `import-graph.py` | 195 | Language-specific importers | **KEEP** | Dep graph backend |
| `items.py` | 520 | Inline-item graph manager | **KEEP** | Complex but critical |
| `items_verify.py` | 140 | Item consistency checker | **KEEP** | Validates items.py |
| `jira_sync.py` | 185 | Jira API integration | **KEEP** | External integration |
| `lifecycle.py` | 250 | State machine logic | **KEEP, REFACTOR** | Overlap with phases.py |
| `module_writer.py` | 310 | CLAUDE.md per-module gen | **KEEP** | Docgen core |
| `phase_completion.py` | 200 | Artefact completion check | **KEEP, EXTEND** | Needs more phase checkers |
| `phases.py` | 180 | Phase metadata from yml | **KEEP, REFACTOR** | Overlap with lifecycle.py |
| `runner.py` | 290 | Agent invocation CLI | **KEEP, REFACTOR** | Overlap with lifecycle.py |
| `scratch.py` | 165 | Scratchpad I/O | **KEEP** | Agent overflow |
| `serena.py` | 410 | Legacy orchestrator | **DELETE** | Replaced by runner.py |
| `serena-call-graph.py` | 125 | Serena helper | **DELETE** | Part of serena |
| `stale_tracker.py` | 95 | Stale file detector | **KEEP** | Index maintenance |
| `task_graph.py` | 220 | Build step DAG | **KEEP** | Build orchestration |
| `test_runner.py` | 175 | Test execution wrapper | **KEEP** | Build phase |
| `ticket_readme.py` | 85 | README.md generator | **KEEP** | Per-ticket summary |
| `validator.py` | 190 | Legacy spec validator | **MERGE** | Into phase_completion.py |
| `xref.py` | 140 | Cross-reference resolver | **KEEP** | Build context |
| `yaml_merge.py` | 75 | Config override merger | **MERGE** | Into _yaml.py |

**`.bak` files found:**
- `callgraph_rust_pattern.py.bak` → **DELETE**

**Duplication patterns:**
1. **YAML loading**: `_yaml.py` + local loaders in 5 files → extract to `_yaml.py`
2. **Path resolution**: Duplicated in 8 files → use `_paths.py` consistently
3. **Artefact writes**: 12 files re-implement write-with-frontmatter → use `artefacts.py`
4. **CLI arg parsing**: Inconsistent (`--out` vs `--output`, positional vs named) → standardize
5. **Lifecycle state queries**: `runner.py`, `lifecycle.py`, `phases.py` all read `meta.json` → unify

### core/phases/ (13 files)

| File | LOC | Purpose | Disposition | Notes |
|------|-----|---------|-------------|-------|
| `__init__.py` | 5 | Package marker | **KEEP** | - |
| `abort.py` | 45 | Cancel ticket | **KEEP** | Thin wrapper |
| `ack.py` | 180 | Confirm phase work | **KEEP** | State machine core |
| `board.py` | 95 | Show all tickets | **KEEP** | CLI convenience |
| `doctor.py` | 120 | Health check | **KEEP** | Diagnostic |
| `install.py` | 210 | Bootstrap project | **KEEP** | Setup infrastructure |
| `intake.py` | 165 | Create ticket | **KEEP** | Entry point |
| `jira_sync_cmd.py` | 85 | Jira sync wrapper | **KEEP** | External integration |
| `jump.py` | 140 | Force phase change | **KEEP** | Power-user tool |
| `next.py` | 75 | Advance phase | **KEEP** | Thin wrapper |
| `ship.py` | 95 | Ack + next atomic | **KEEP** | Convenience |
| `status.py` | 110 | Show ticket state | **KEEP** | CLI core |
| `step.py` | 85 | TDD step card (build) | **KEEP** | Build iteration |

**All phase commands are thin wrappers over `core/skills/`. No refactoring needed.**

### scripts/ (5 files)

| File | LOC | Purpose | Disposition | Notes |
|------|-----|---------|-------------|-------|
| `init.py` | 450 | Deterministic index | **KEEP** | Index builder |
| `install_deps.py` | 95 | Dependency installer | **KEEP** | Setup script |
| `klc` | 180 | CLI dispatcher | **KEEP** | Entry point |
| `review-runner.py` | 210 | Review orchestrator | **KEEP** | Multi-agent runner |
| `review.py` | 165 | Review sub-agent | **KEEP** | Review logic |
| `update.py` | 380 | Incremental index update | **KEEP** | Index maintenance |

**No refactoring needed in scripts/.**

## Shared Helpers to Extract

### 1. YAML utilities → expand `_yaml.py`

Currently 45 LOC. Add:
- `load_with_defaults(path, defaults_dict)` — merge user config with defaults
- `validate_schema(data, required_keys)` — validate loaded YAML

**Impact**: Remove duplication from 5 files (~120 LOC reduction)

### 2. Path utilities → expand `_paths.py`

Currently 120 LOC. Add:
- `ensure_parent_dir(path)` — mkdir -p parent
- `safe_write(path, content)` — atomic write with backup

**Impact**: Remove duplication from 8 files (~180 LOC reduction)

### 3. Artefact I/O → expand `artefacts.py`

Currently 180 LOC. Ensure all write-with-frontmatter uses `write_artefact()`.

**Impact**: Remove duplication from 12 files (~200 LOC reduction)

### 4. CLI conventions → document + enforce

**Current**: Inconsistent arg names  
**Target**: Standardize to:
- `--ticket <KEY>` (required for ticket-scoped skills)
- `--out <PATH>` (output file)
- `--root <PATH>` (project root, or use `PROJECT_ROOT` env)
- Exit codes: 0 = success, 1 = user error, 2 = internal error

**Impact**: Consistency, no LOC change

### 5. Lifecycle/phases/runner overlap → clarify ownership

**Current state:**
- `lifecycle.py`: Read/write `meta.json`, state transitions
- `phases.py`: Parse `config/phases.yml`, phase metadata
- `runner.py`: Invoke agents, also reads `meta.json`
- `phase_completion.py`: Check artefacts

**Target state:**
- `lifecycle.py`: **Only** state machine (current phase, transitions, write meta.json)
- `phases.py`: **Only** phase metadata (from phases.yml)
- `runner.py`: **Only** agent invocation (delegates state queries to lifecycle.py)
- `phase_completion.py`: **Only** artefact validation

**Impact**: Clearer boundaries, minimal LOC change (~50 LOC reduction via de-duplication)

## Estimate

### Discovery phase (current)
- **Effort**: 2 days (audit table complete)
- **Deliverable**: This spec.md

### Build phase (post-KLC-006)
- **Effort**: 5 days
- **Deletions**: `serena.py`, `serena-call-graph.py`, `.bak` files (~535 LOC)
- **Extractions**: Shared helpers to `_paths.py`, `_yaml.py` (~300 LOC reduction via de-duplication)
- **Refactoring**: lifecycle/phases/runner clarification (~50 LOC reduction)
- **Total LOC reduction**: ~885 LOC / ~6200 total = **14% reduction** ✓ exceeds AC-7 (10%)

## Non-goals

- Performance tuning
- New functionality
- Rewriting agent prompts

## Constraints

- Must maintain backward compatibility (existing tickets in-flight)
- `tests/smoke.py` must pass unchanged
- No new imports from `scripts/` into `core/skills/`

## Affected modules

- `core/skills/` (35 files, 14% LOC reduction target)
- `core/phases/` (13 files, no changes needed)
- `scripts/` (5 files, no changes needed)

## Open questions

None — audit complete.

## Related

- **Depends on**: KLC-008 (E2E tests provide safety net)
- **Paused after discovery**: Build phase resumes post-KLC-006 (docs define CLI conventions)
- **Parallel with**: KLC-009 (config cleanup, no file overlap)
