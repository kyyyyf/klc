---
ticket: KLC-007
authority: human
decision_date: 2026-05-28T14:00:00Z
chosen_option: B
---

# Architecture Decision Record — KLC-007

## Decision

**Chosen**: Option B — Clean architecture (extract shared helpers)

## Context

Code audit (spec.md) identified significant duplication:
- YAML loading: 5 files (~120 LOC)
- Path resolution: 8 files 
- Artefact writes: 12 files
- Lifecycle state queries: 3 files (runner, lifecycle, phases)

Option A (minimal diff) would leave technical debt. Option C (plugin system) is overengineering. Option B balances cleanup with manageable scope.

## Rationale

### Why Option B over Option A
1. **Addresses root cause**: Duplication identified in AC-2, AC-4. Option A ignores it.
2. **Long-term maintainability**: New skills will use `core/shared/` helpers, preventing future duplication.
3. **Reduces LOC more**: Option A saves 535 LOC (deletions only). Option B saves ~700-800 LOC (deletions + deduplication).
4. **Cleaner API surface**: Consolidating helpers clarifies what's shared vs skill-specific.

### Why Option B over Option C
1. **Scope control**: Option C (40-60h) is 2.5x Option B (24-32h) with unclear ROI.
2. **No product requirement**: Plugin architecture not in spec, not requested by PM.
3. **Risk management**: Option B has phased rollout (3 PRs), easier to rollback than Option C (6 PRs).

## Consequences

### Positive
- ✅ 700-800 LOC reduction (vs 535 for Option A)
- ✅ `core/shared/` becomes reusable across skills
- ✅ Future skills have clean API (yaml, paths, artefacts)
- ✅ Clearer module boundaries (shared vs skill-specific)

### Negative
- ⚠️ 20-30 import updates (higher merge conflict risk than Option A)
- ⚠️ Longer dev time (24-32h vs 12-16h for Option A)
- ⚠️ Module index rebuild required (`.klc/index/modules.json`)
- ⚠️ More comprehensive testing needed (all skills must be validated)

### Mitigation strategies
1. **Phased rollout**: 3 PRs (create shared, migrate imports, delete old)
2. **E2E tests**: Run `tests/e2e_pipeline.py` after each PR
3. **Smoke tests**: Run `tests/smoke.py` after each merge
4. **Import validation**: Automated grep for old import paths before final merge

## Alternatives considered

### Option A (Minimal diff) — REJECTED
- **Pros**: Lower risk, faster (12-16h), small diff
- **Cons**: Leaves duplication, doesn't address AC-4 (shared helpers)
- **Why rejected**: Doesn't solve root problem, just removes dead code

### Option C (Plugin system) — REJECTED
- **Pros**: Future-proof, standardized skill interface
- **Cons**: Massive scope (40-60h), breaks existing agent prompts, no product requirement
- **Why rejected**: Overengineering for cleanup ticket, not in spec

## Implementation plan (high-level)

### Phase 1: Create `core/shared/` module
- Extract YAML utilities to `core/shared/yaml.py`
- Extract path utilities to `core/shared/paths.py`
- Extract artefact utilities to `core/shared/artefacts.py`
- Add unit tests for each module
- **Deliverable**: PR #1

### Phase 2: Migrate skills to use `core/shared/`
- Update 20-30 import statements
- Run smoke tests after each batch (5-10 skills)
- Validate E2E pipeline passes
- **Deliverable**: PR #2

### Phase 3: Delete old files, merge duplicates
- Delete serena.py, serena-call-graph.py, *.bak
- Merge validator.py → phase_completion.py
- Merge yaml_merge.py → _yaml.py (or deprecate if redundant with core/shared/yaml)
- Final smoke + E2E tests
- **Deliverable**: PR #3

### Phase 4: Module index rebuild
- Run `scripts/init.py` to rebuild `.klc/index/`
- Verify no broken imports in index
- **Deliverable**: Included in PR #3

## Validation criteria

Before merging each PR:
- [ ] `tests/smoke.py` passes (all 14 blocks)
- [ ] `python tests/e2e_pipeline.py` passes (all 4 tracks)
- [ ] No import errors when running `klc status`, `klc ack`
- [ ] Module index reflects new structure (`core.shared` module present)

## Rollback plan

If Phase 2 (import migration) causes issues:
1. Revert PR #2 commits
2. `core/shared/` module remains (unused, no harm)
3. Skills continue using old imports
4. Reassess in retrospective (consider Option A for next attempt)

## Decision authority

**Decided by**: Human (user choice: "давай опцию 2")  
**Agent recommendation**: Option A (minimal diff)  
**Final decision**: Option B (human override of agent recommendation)

## Related decisions

- **Defers**: Option C plugin architecture → future ticket if product needs change
- **Unblocks**: KLC-009 (config cleanup) can proceed after this refactor
- **Depends on**: KLC-006 (documentation) already archived ✓
