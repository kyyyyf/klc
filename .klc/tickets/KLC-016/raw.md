---
ticket: KLC-016
kind_hint: feature
created: 2026-05-29T13:09:15Z
---
Phase 5 — token telemetry & budget guard. Parse usage from Anthropic response in core/skills/runner.py (--output-format json or API usage field); store tokens_in/out/cache_hit in meta.json:metrics.tokens.<phase>. Budget guard at compose stage: if prompt > limits[track] -> refuse run, write [!QUESTION] context too large. New config/budgets.yml: prompt_input_limits per track. Update core/skills/metrics.py rollup (tokens per track/phase). klc metrics --rollup shows averages. See plan.md Phase 5.
