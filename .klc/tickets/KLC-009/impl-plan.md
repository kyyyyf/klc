---
ticket: KLC-009
authority: agent
last_generated: 2026-05-28T14:26:00Z
---

# Implementation plan — KLC-009

## Approach

Sequential cleanup and enhancement of config/ directory. No architectural changes needed — pure cleanup + validation addition.

## Steps

### step-1: Move severity-rubric.md to docs/
**What**: `mv config/severity-rubric.md docs/severity-rubric.md`  
**Why**: It's documentation, not runtime config (AC-4)  
**Files**: `config/severity-rubric.md` → `docs/severity-rubric.md`  
**Validation**: File exists at new location, not at old location

### step-2: Add header comments to all config files
**What**: Add consumer documentation to each YAML file header  
**Why**: Make config ownership explicit (AC-3)  
**Files**:
- `config/phases.yml` — add "Consumed by: core/skills/phases.py, core/skills/lifecycle.py, core/skills/artefacts.py"
- `config/models.yml` — add "Consumed by: core/skills/models.py"
- `config/tiers.yml` — add "Consumed by: core/skills/classify_tier.py"
- `config/sentinels.yml` — add "Consumed by: core/skills/scan_sentinels.py"
- `config/reviewers.yml` — add "Consumed by: core/skills/review.py"
- `config/jira.yml` — add "Consumed by: core/skills/jira_sync.py"
- `config/ticket-id.yml` — add "Consumed by: core/phases/intake.py"
- `config/profile.yml` — add "Consumed by: core/phases/install.py, core/phases/doctor.py, core/skills/profile-resolve.py"
- `config/reviewer-allowlist.seed.yml` — add "Seed file - copied to .klc/knowledge/reviewer-allowlist.yml during install"

**Validation**: Each file has header comment above YAML content

### step-3: Standardize naming in tiers.yml and sentinels.yml
**What**: Ensure consistent snake_case in both files  
**Why**: Config consistency  
**Files**: `config/tiers.yml`, `config/sentinels.yml`  
**Validation**: All keys use snake_case (no camelCase or kebab-case)

### step-4: Create core/skills/validate_config.py
**What**: New skill that validates config YAML against known schemas  
**Why**: Catch unknown keys early (AC-5)  
**Files**: `core/skills/validate_config.py` (new)  
**Implementation**:
- Define expected keys for each config file (phases.yml, models.yml, tiers.yml, etc.)
- Load each config file and check for unknown keys
- Return warnings (not errors) for unknown keys
- Skip seed files (reviewer-allowlist.seed.yml)

**Validation**: Skill can be imported and run; warns on unknown keys

### step-5: Integrate validate_config into klc doctor
**What**: Call validate_config.py from doctor.py  
**Why**: Make validation accessible via `klc doctor` (AC-5)  
**Files**: `core/phases/doctor.py`  
**Validation**: `klc doctor` output includes config validation warnings

### step-6: Create config/README.md
**What**: Index of all config files with their purposes  
**Why**: Documentation for future maintainers  
**Files**: `config/README.md` (new)  
**Content**:
- Table with: filename, purpose, consumer(s), line count
- Brief explanation of seed files vs runtime files

**Validation**: README exists and lists all config files

## Dependencies between steps

- step-2 can run in parallel with step-1
- step-3 can run in parallel with step-1 and step-2
- step-4 must complete before step-5
- step-6 is independent, can run anytime

## Risks

- **Low risk**: Pure cleanup, no logic changes
- **Mitigation**: Run full test suite (AC-6) after each step

## Rollback

Git revert is sufficient — no database migrations or external dependencies.
