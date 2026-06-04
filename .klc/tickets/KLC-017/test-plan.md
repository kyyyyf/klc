---
ticket: KLC-017
kind: tech
authority: agent
---

# KLC-017 — Test plan

## Acceptance coverage

### AC-1: compressed card does not embed impl.md

| # | Given | When | Then |
|---|-------|------|------|
| 1.1 | a ticket with spec.md + impl-plan.md, `impl.md` exists on disk | `write_step_card(ticket, step=1, meta)` called in default mode | output file does NOT contain the text of `impl.md`; DOES contain a `## Role prompt` section with the path reference |
| 1.2 | same setup | output file read | contains text like `Read the role prompt at` + absolute/relative path to `core/agents/impl.md` |
| 1.3 | `impl.md` does not exist on disk | `write_step_card()` in default mode | graceful: card still generated, missing-file note in role-prompt section |

### AC-2: inline mode embeds impl.md

| # | Given | When | Then |
|---|-------|------|------|
| 2.1 | same setup | `write_step_card(..., inline=True)` | output DOES contain full text of `impl.md` |
| 2.2 | env var `KLC_CARD_INLINE=1` set | `write_step_card()` without explicit arg | behaves as inline=True (embeds) |
| 2.3 | env var unset | `write_step_card()` without explicit arg | behaves as compressed (default) |

### AC-3: telemetry source field

| # | Given | When | Then |
|---|-------|------|------|
| 3.1 | claude CLI returns JSON with `usage.input_tokens` | `run_agent()` parses response | `meta.json:metrics.tokens.<phase>.source == "provider"` |
| 3.2 | claude CLI returns plain text (no JSON usage block) | `run_agent()` estimates via `len//4` | `meta.json:metrics.tokens.<phase>.source == "estimated"` |
| 3.3 | plain-text response (estimated) | telemetry written | `cache_hit == 0` (never non-zero for estimated) |
| 3.4 | JSON with `cache_read_input_tokens > 0` | telemetry written | `source == "provider"`, `cache_hit > 0` |

### AC-4: rollup surfaces source

| # | Given | When | Then |
|---|-------|------|------|
| 4.1 | tickets with mix of provider/estimated tokens | `klc metrics rollup` | output JSON contains `source_counts: {provider: N, estimated: M}` per phase |
| 4.2 | all estimated tickets | rollup output | no claim of exact provider usage; `source_counts.provider == 0` |

### AC-5: before/after size recorded

| # | Given | When | Then |
|---|-------|------|------|
| 5.1 | one build-step fixture | compressed card generated | card byte size < inline card byte size by ≥ 5 000 bytes (impl.md is 7 476 bytes) |
| 5.2 | same fixture | both modes | difference recorded in test assertion output (visible in CI log) |

### AC-6: preamble trim (non-blocking)

| # | Given | When | Then |
|---|-------|------|------|
| 6.1 | `_PREAMBLE_TMPL` inspected | static check | no duplicated ticket/track info that is already in the card header |

## Edge cases

| # | Scenario | Expected behaviour |
|---|----------|--------------------|
| E-1 | `impl.md` path reference in compressed card — agent cannot read filesystem | Card includes explicit instruction: "Before acting, read the role prompt at `<path>`. If you cannot access it, re-run with `KLC_CARD_INLINE=1`." |
| E-2 | `write_step_card()` called with `inline=True` AND `KLC_CARD_INLINE=0` (conflicting) | explicit arg wins over env var |
| E-3 | rollup with zero tickets having token metrics | rollup does not crash; `tokens_by_phase` is empty dict |
| E-4 | `source` field added to existing meta.json that has `tokens` without `source` | migration: missing `source` treated as `"estimated"` in rollup |
| E-5 | `_PREAMBLE_TMPL` trimming removes a field another code path relies on | `smoke.py` and e2e still pass |
