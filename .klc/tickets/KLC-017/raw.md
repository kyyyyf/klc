---
ticket: KLC-017
kind_hint: tech
created: 2026-05-29T13:09:20Z
---
Phase 6 — token sweep (prompt caching, compressed cards). Stop embedding full impl.md into each step card in core/skills/artefacts.py:279 — replace with read-once reference. Wrap stable prompt parts with cache_control: ephemeral for Anthropic in core/skills/runner.py; record cache_hit in telemetry. Trim _PREAMBLE_TMPL duplication. Compare tokens before/after using KLC-016 metrics; record numbers in retrospective. Depends on KLC-016 telemetry. See plan.md Phase 6.
