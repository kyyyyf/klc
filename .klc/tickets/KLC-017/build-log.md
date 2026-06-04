---
ticket: KLC-017
phase: build
authority: agent
---

# KLC-017 build log

## Step 1 — compressed step cards + telemetry source

**Outcome**: green

**Changes made**:
- `core/skills/artefacts.py`: `write_step_card()` gains `inline` param
  (bool|None). Default None → read `KLC_CARD_INLINE` env var; False →
  compressed (path reference); True → embed full `impl.md`. Explicit
  arg wins over env var. `_PREAMBLE_TMPL` trimmed (removed duplicate
  ticket/track that was already in the card header).
- `core/templates/impl-step.md.j2`: role-prompt section now branches on
  `impl_prompt` vs `impl_prompt_ref`. Compressed mode renders a path
  reference with "Before acting, read…" instruction and `KLC_CARD_INLINE=1`
  escape hatch.
- `core/skills/runner.py`: `_write_token_metrics()` gains `source` param
  (`"provider"` or `"estimated"`). `run_agent()` sets source based on
  whether `_parse_usage_from_output()` returned a real usage block.
  `cache_hit` is zeroed for `estimated` source.
- `core/skills/metrics.py`: token rollup now collects `source` field per
  sample and emits `source_counts: {provider, estimated}` per phase.
- `tests/integration/test_step_card_compression.py` (new): 7 tests —
  compressed/inline content, env var, arg priority, size delta, telemetry
  source. All green.
- `docs/process.md`: Build phase section updated with compressed-card
  default; token telemetry section updated with `source` field and
  `source_counts` rollup.

**Metrics**: compressed card = 1 651 B vs inline = 8 828 B → 7 177 B
(≈7.0 KB) saved per step. impl.md = 7 476 B.
