---
ticket: KLC-014
kind_hint: feature
created: 2026-05-29T13:08:16Z
---
Phase 3 — conditional phases. Add condition: <expr> field on phase definition in phases.yml (minimal expr language: meta.<path> + in/not in/>=/>/==). Skip phase if condition is False (record phase_history event=skipped). observe condition: meta.risk_tags contains user-facing/data/security/migration. learn condition: rework_count>0 OR regression_observed OR budgets.any_overrun. Make discovery and discovery-lite emit risk_tags into meta.json. See plan.md Phase 3.
