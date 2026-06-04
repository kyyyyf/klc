---
ticket: KLC-015
kind_hint: feature
created: 2026-05-29T13:08:18Z
---
Phase 4 — review cascade. New core/skills/review_cascade.py (or extend scripts/review.py): pipeline scope_delta -> scan_sentinels -> classify_tier. Peripheral tier + no sentinels + no scope drift -> single cheap reviewer (Sonnet, focused diff). Critical tier or sentinel hits -> current full multi-agent review. Update models.yml: review for S=coding, M=coding+cascade-trigger, L=current cascade. Add cascade.enabled flag in reviewers.yml. Integration test: peripheral diff doesn't trigger full review. See plan.md Phase 4.
