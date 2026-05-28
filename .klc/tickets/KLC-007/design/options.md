---
ticket: KLC-007
authority: agent
generated: 2026-05-28T13:50:00Z
---

# Design options — KLC-007

## Context

Code audit identified 535 LOC for deletion (serena.py, serena-call-graph.py, *.bak) and merge opportunities (validator.py → phase_completion.py, yaml_merge.py → _yaml.py). Need design approach for safe refactoring across 3 modules (core/skills, core/phases, scripts).

## Option A — Minimal diff (file-by-file cleanup)

**recommended: true**

### Trade-off
Lowest risk, minimal code churn, but doesn't address structural issues (duplicate helpers still scattered).

### Approach
1. Delete dead files first (serena.py, *.bak) — no dependencies
2. Merge small files one-by-one (validator.py → phase_completion.py)
3. Update imports incrementally
4. Run tests/smoke.py after each merge

### Affected files
- **DELETE**: `core/skills/serena.py`, `core/skills/serena-call-graph.py`, `core/skills/*.bak` (3 files)
- **MERGE**: `core/skills/validator.py` → `core/skills/phase_completion.py`, `core/skills/yaml_merge.py` → `core/skills/_yaml.py` (2 merges)
- **UPDATE**: Import statements in 8-10 files referencing merged/deleted files

### Affected public APIs
- `core.skills.validator` module removed (functions moved to `phase_completion`)
- `core.skills.yaml_merge` module removed (functions moved to `_yaml`)
- No external API changes (internal refactor only)

### New dependencies
None.

### Risks
- Missed imports (grep may not catch dynamic imports)
- Merge conflicts if files diverged (validator vs phase_completion logic)
- Test coverage gaps (some skills have no tests)

### Rollout
Immediate (single PR, no feature flag needed).

### Estimate
**M** (12-16 hours)
- Delete files: 2h (verify no imports, delete, commit)
- Merge validator.py: 4h (move functions, update imports, test)
- Merge yaml_merge.py: 3h (consolidate logic, test)
- Import updates: 2h (grep, sed, verify)
- Smoke tests + manual validation: 3h

---

## Option B — Clean architecture (extract shared helpers)

### Trade-off
Cleaner code structure with extracted helpers (`core/shared/`), but higher risk (new module, more imports changed).

### Approach
1. Create `core/shared/` module for common utilities (yaml, paths, artefacts)
2. Extract duplicate logic from skills into shared helpers
3. Update all skills to import from `core/shared/`
4. Delete/merge files as in Option A
5. Add `core/shared/` to module index

### Affected files
- **NEW MODULE**: `core/shared/yaml.py`, `core/shared/paths.py`, `core/shared/artefacts.py` (3 new files)
- **DELETE**: Same as Option A (serena, *.bak)
- **MERGE**: Same as Option A (validator, yaml_merge)
- **UPDATE**: 20-30 import statements across all skills

### Affected public APIs
- New public module: `core.shared` (YAML, path, artefact utilities)
- Deprecate `core.skills._yaml`, `core.skills._paths` (redirect to `core.shared`)
- No external API changes (internal refactor)

### New dependencies
None (pure refactor).

### Risks
- Large import churn (20-30 files changed) increases merge conflict risk
- Circular dependency if `core.shared` imports from `core.skills`
- Module index rebuild required (`.klc/index/modules.json`)
- Higher test burden (must validate all skills still work)

### Rollout
Phased:
1. PR1: Create `core/shared/`, move utilities
2. PR2: Update skills to use `core/shared/`
3. PR3: Delete/merge old files

### Estimate
**L** (24-32 hours)
- Create `core/shared/`: 6h (extract logic, test)
- Update imports: 8h (20-30 files, verify each)
- Delete/merge files: 5h (same as Option A)
- Rebuild index: 2h (modules.json, symbols_by_module.json)
- Comprehensive testing: 6h (smoke + unit tests)

---

## Option C — Scalability (modular skill architecture)

### Trade-off
Future-proof skill plugin system, but massive overengineering for this ticket's scope (audit only, not full rewrite).

### Approach
1. Design skill plugin interface (`BaseSkill` abstract class)
2. Convert all skills to plugins with standardized CLI entry points
3. Create skill registry (`core/skills/registry.py`)
4. Refactor `scripts/klc` to use registry
5. Extract shared helpers as in Option B
6. Delete/merge files as in Option A

### Affected files
- **NEW MODULE**: `core/skills/registry.py`, `core/skills/base.py` (plugin interface)
- **REFACTOR**: All 35 skills to inherit from `BaseSkill`
- **SHARED**: Same as Option B (`core/shared/`)
- **DELETE/MERGE**: Same as Option A

### Affected public APIs
- Major breaking change: All skill CLIs must use new plugin interface
- New public API: `core.skills.registry.SkillRegistry`
- Deprecate direct skill imports (must go through registry)

### New dependencies
None (pure refactor, but large scope).

### Risks
- Massive scope creep (not in original spec)
- High regression risk (all skills refactored)
- Long dev time conflicts with other tickets (KLC-006, KLC-009)
- Breaks existing agent prompts referencing direct skill paths

### Rollout
Multi-phase (4-6 PRs):
1. Plugin interface + registry
2. Convert 10 skills (pilot)
3. Convert remaining 25 skills
4. Extract shared helpers
5. Delete/merge old files
6. Update agent prompts

### Estimate
**XL** (40-60 hours)
- Plugin design: 8h (interface, registry, tests)
- Convert skills: 24h (35 skills × ~40min each)
- Shared helpers: 6h (same as Option B)
- Delete/merge: 5h (same as Option A)
- Comprehensive testing: 12h (all skills, integration tests)
- Documentation updates: 5h (agent prompts, CLAUDE.md)

---

## Recommendation

**Option A (Minimal diff)** is recommended for KLC-007 because:

1. **Scope alignment**: Ticket spec says "audit phase only", build is post-KLC-006. Option A delivers 14% LOC reduction (535 LOC / ~6200 total) with minimal risk.

2. **Unblocks dependencies**: KLC-006 (docs) and KLC-009 (config) are in-flight. Option A has small diff surface, low merge conflict risk.

3. **Incremental safety**: File-by-file approach allows rollback at each step. Tests run after each merge.

4. **Time vs value**: Option B (+12-16h) and Option C (+28-44h) don't deliver proportional value for this ticket's goals. Structural improvements can be separate tickets if needed.

**Defer to future tickets**:
- Option B (shared helpers) → KLC-010 (if code duplication becomes painful)
- Option C (plugin architecture) → Out of scope unless product requirements change
