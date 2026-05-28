---
ticket: KLC-009
kind_hint: tech
created: 2026-05-28T11:15:13Z
---
# KLC-009 — Configuration cleanup and audit

## Context

`config/` accreted across Phases 1–4 (10 files, ~865 lines):
- `jira.yml`, `models.yml`, `phases.yml` (300 lines), `profile.yml`,
  `reviewer-allowlist.seed.yml`, `reviewers.yml`, `sentinels.yml` (183 lines),
  `severity-rubric.md`, `ticket-id.yml`, `tiers.yml` (118 lines)

No audit done since Phase 1. Likely contains: dead entries, unused keys, legacy options no skill consumes.

## Problem

Specific suspected issues (need verification):
1. **Dead config keys**: entries in `phases.yml` / `tiers.yml` that no `core/skills/` reads
2. **Inconsistent schemas**: `tiers.yml` and `sentinels.yml` may use different conventions for similar concepts
3. **Seed vs runtime**: `reviewer-allowlist.seed.yml` is a seed file but unclear when it's regenerated vs `reviewer-allowlist.yml`
4. **Profile resolution**: `profile.yml` references `profiles/<name>/` but resolution path is unclear
5. **Defaults scattered**: each YAML has its own defaults, no single "what does the framework assume by default?"

## Proposed solution

**Step 1 — Audit (discovery)**:
- For each YAML key in `config/*.yml`: grep `core/`, `scripts/` for the key name
- Mark each: `used` / `dead` / `aliased` (used under different name)
- Build dependency map: which skill reads which config file

**Step 2 — Cleanup (build)**:
- Delete dead keys
- Document every remaining key inline (`# what this controls; consumed by <skill>`)
- Standardize naming: snake_case across all configs (current state mixed)
- Add `config/README.md` or expand `docs/phases/*.md` (from KLC-006) with config index
- Move any `.md` content out of `config/` (severity-rubric.md → `docs/`)

**Step 3 — Validation**:
- Add `core/skills/validate_config.py`: schema-checks every YAML on `klc doctor`
- `klc doctor` warns on unknown keys (not silent ignore)

## Acceptance criteria

- AC-1: Audit table in `discovery.md` lists every config key with `used / dead` status and consumer
- AC-2: All dead keys removed; commit shows what was deleted and why
- AC-3: Each remaining config file has a header comment naming consumer skill(s)
- AC-4: `severity-rubric.md` moved out of `config/` (it's docs, not config)
- AC-5: `klc doctor` warns on unknown YAML keys
- AC-6: `tests/smoke.py` and `tests/e2e_pipeline.py` (KLC-008) pass unchanged
- AC-7: Line count reduction ≥15% in `config/` (soft target)

## Out of scope

- Migrating config format (stay YAML; no TOML/JSON conversion)
- Per-profile config overrides redesign (separate ticket if needed)
- Schema definition language (JSON Schema / pydantic) — manual validation acceptable for now

## Estimate

- Complexity: 2 (audit + delete; no new logic)
- Uncertainty: 2 (don't yet know how much is dead)
- Risk: 1 (deleting "dead" key that's actually used in CI)
- Manual: 1 (re-run smoke + e2e)
- Total: 6
- Track: S/M

## Related

- **Depends on KLC-008** (e2e tests as safety net)
- **Coordinates with KLC-006** (docs/phases/ should reference cleaned config)
- Independent of KLC-007 (can run in parallel after KLC-008 lands)

## Notes

Order: KLC-006 → KLC-008 → (KLC-007 ∥ KLC-009).
