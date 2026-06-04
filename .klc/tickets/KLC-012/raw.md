---
ticket: KLC-012
kind_hint: tech
created: 2026-05-29T13:08:06Z
---
Phase 1 — quality gates. Make phase_completion strict (default: check phase.outputs from phases.yml). Add scope_delta.py: compares meta.affected_modules with git diff, blocks review/integrate on expansion. Make e2e_pipeline.py config-driven (read paths from phases.yml) with negative tests for missing outputs. Wire validate_config.validate_all() into klc doctor. See plan.md Phase 1.
