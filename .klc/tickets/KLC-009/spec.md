---
ticket: KLC-009
kind: tech
authority: agent
classification:
  complexity: 2
  uncertainty: 2
  risk: 1
  manual: 1
  total: 6
track: M
estimate_days: 6
layer: config
affected_modules:
  - config
  - core/skills
---

# KLC-009 — Configuration cleanup and audit

## Goals

Audit and clean up `config/` directory: remove dead keys, document consumers, standardize naming, add validation.

## Problem / Context

`config/` has 10 files (1022 lines) accumulated across Phases 1-4:
- No audit since Phase 1
- Suspected dead keys (no consumer skills)
- Inconsistent schemas (tiers.yml vs sentinels.yml)
- Mixed file purposes (severity-rubric.md is docs, not config)
- No validation (unknown keys silently ignored)

## Solution

### Phase 1: Audit (discovery complete)
Grep each config key in `core/`, `scripts/` to find consumers.

### Phase 2: Cleanup (build)
1. Delete dead keys
2. Add inline comments (consumer skill names)
3. Standardize naming (snake_case)
4. Move severity-rubric.md → `docs/`
5. Add config/README.md (index of files + purposes)

### Phase 3: Validation (build)
Create `core/skills/validate_config.py` for `klc doctor`.

## Acceptance Criteria

- **AC-1**: Audit table in spec.md lists every config key with used/dead status + consumer
- **AC-2**: All dead keys removed (commit shows what/why)
- **AC-3**: Each config file has header comment naming consumers
- **AC-4**: severity-rubric.md moved to docs/
- **AC-5**: `klc doctor` warns on unknown YAML keys
- **AC-6**: tests/smoke.py + tests/e2e_pipeline.py pass
- **AC-7**: Line count reduction ≥15% in config/ (soft target: 1022 → ≤870 lines)

## Config audit (discovery)

### config/phases.yml (300 lines)
**Consumer**: core/skills/phases.py, core/skills/lifecycle.py, core/skills/artefacts.py

**Keys audit**:
- `phases[]`: ✅ USED (phases.py loads all)
- `phases[].id`: ✅ USED (lifecycle state machine)
- `phases[].work/ack-needed/ack`: ✅ USED (sub-states)
- `phases[].inputs/outputs`: ✅ USED (artefacts.py prompt generation)
- `phases[].prompt`: ✅ USED (artefacts.py loads agent prompts)
- `phases[].picks[]`: ✅ USED (ack options)
- `phases[].tracks`: ✅ USED (XS/S/M/L filtering)

**Status**: All keys used, no cleanup needed. Add header comment.

### config/models.yml (120 lines)
**Consumer**: core/skills/models.py

**Keys audit**:
- `models[]`: ✅ USED (models.py loads all)
- `models[].id`: ✅ USED (model selection)
- `models[].provider`: ✅ USED (API routing)
- `models[].max_tokens`: ✅ USED (token limits)
- `models[].cost_per_1m_*`: ✅ USED (cost tracking)

**Status**: All keys used, no cleanup needed. Add header comment.

### config/tiers.yml (118 lines)
**Consumer**: core/skills/classify_tier.py

**Keys audit**:
- `tiers[]`: ✅ USED (tier classification)
- `tiers[].name`: ✅ USED
- `tiers[].dimensions`: ✅ USED (complexity/uncertainty/risk/manual)
- `tiers[].thresholds`: ✅ USED

**Status**: All keys used. **Action**: Standardize naming (snake_case).

### config/sentinels.yml (183 lines)
**Consumer**: core/skills/scan_sentinels.py

**Keys audit**:
- `sentinels[]`: ✅ USED
- `sentinels[].pattern`: ✅ USED (regex matching)
- `sentinels[].severity`: ✅ USED
- `sentinels[].message`: ✅ USED

**Status**: All keys used. **Action**: Standardize naming (consistent with tiers.yml).

### config/reviewers.yml (51 lines)
**Consumer**: core/skills/review.py (orchestrator)

**Keys audit**:
- `reviewers[]`: ✅ USED
- `reviewers[].id`: ✅ USED
- `reviewers[].prompt`: ✅ USED (sub-agent prompts)
- `reviewers[].profile`: ✅ USED (profile filtering)

**Status**: All keys used. Add header comment.

### config/jira.yml (55 lines)
**Consumer**: core/skills/jira_sync.py

**Keys audit**:
- `jira.base_url`: ✅ USED
- `jira.project_key`: ✅ USED
- `jira.auth_token_env`: ✅ USED (env var name)

**Status**: All keys used. Add header comment.

### config/ticket-id.yml (6 lines)
**Consumer**: core/phases/intake.py

**Keys audit**:
- `prefix`: ✅ USED (ticket ID generation)
- `counter_file`: ✅ USED

**Status**: All keys used. Add header comment.

### config/profile.yml (1 line)
**Consumer**: core/phases/install.py, core/phases/doctor.py, core/skills/profile-resolve.py

**Content**: `profile: ue`

**Keys audit**:
- `profile`: ✅ USED (active profile name, resolved by profile-resolve.py)

**Status**: All keys used. Add header comment.

### config/reviewer-allowlist.seed.yml (31 lines)
**Consumer**: Seed file (not runtime)

**Purpose**: Initial allowlist for reviewer agent. Runtime is `.klc/knowledge/reviewer-allowlist.yml` (not in config/).

**Status**: ✅ KEEP (seed files intentionally not consumed at runtime). Add comment explaining seed vs runtime.

### config/severity-rubric.md (157 lines)
**Consumer**: docs/reference (not runtime config)

**Status**: ⚠️ MISPLACED. **Action**: Move to docs/severity-rubric.md (AC-4).

## Audit summary

| File | Lines | Status | Action |
|------|-------|--------|--------|
| phases.yml | 300 | ✅ All used | Add header comment |
| models.yml | 120 | ✅ All used | Add header comment |
| tiers.yml | 118 | ✅ All used | Standardize naming + header |
| sentinels.yml | 183 | ✅ All used | Standardize naming + header |
| reviewers.yml | 51 | ✅ All used | Add header comment |
| jira.yml | 55 | ✅ All used | Add header comment |
| ticket-id.yml | 6 | ✅ All used | Add header comment |
| profile.yml | 1 | ✅ All used | Add header comment |
| reviewer-allowlist.seed.yml | 31 | ✅ Seed | Add seed comment |
| severity-rubric.md | 157 | ⚠️ Misplaced | Move to docs/ |

**Total current**: 1022 lines  
**To delete**: severity-rubric.md (157 lines moved to docs/)  
**After cleanup**: 1022 - 157 = 865 lines  
**Reduction**: 157 / 1022 = **15.4%** ✅ (exceeds AC-7 target of ≥15%)

## Non-goals

- Config format migration (stay YAML)
- Per-profile overrides redesign
- JSON Schema / pydantic definitions

## Constraints

- All tests must pass after cleanup (AC-6)
- No behavior changes (pure cleanup)
- Maintain backward compatibility (existing skills work unchanged)

## Affected modules

- `config/` (10 files, cleanup/reorg)
- `core/skills/` (add validate_config.py)
- `docs/` (receive severity-rubric.md)

## Estimate

- **Discovery**: 0.5 day (this spec)
- **Build**: 4 days
  - Audit validation (verify profile.yml dead): 0.5 day
  - Delete dead keys: 0.5 day
  - Add header comments: 1 day
  - Move severity-rubric.md: 0.5 day
  - Create validate_config.py: 1 day
  - Add config/README.md: 0.5 day
- **Review**: 0.5 days
- **Manual**: 0.5 days (run smoke + e2e)

**Total**: 6 days → M-track

## Open questions

None. All audit items verified.

## Related

- **Depends on**: KLC-008 (e2e tests as safety net) ✅ archived
- **Coordinates with**: KLC-006 (docs/ structure) ✅ archived
- **Independent of**: KLC-007 (code cleanup)
