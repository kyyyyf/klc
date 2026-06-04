---
ticket: KLC-017
kind: tech
authority: human
last_generated: 2026-06-04
risk_tags: []
---

# KLC-017 — Token sweep: compressed step cards + honest telemetry

## Goals

Cut the per-build-step prompt size by removing the embedded `impl.md`
role prompt (≈7.5 KB / 186 lines) from every step card, and make
KLC-016 token telemetry distinguish real provider usage from estimates.
Provider prompt caching (`cache_control`) is **descoped** — the current
Anthropic transport (`claude --print` over stdin) cannot attach
cache-control blocks.

## Problem / Context

`core/skills/artefacts.py:write_step_card()` reads the full `impl.md`
(186 lines) and inlines it into `_prompt_step_N.md` for every TDD step
([!FACT src=core/skills/artefacts.py:263-279]). A multi-step build
re-pays that cost on each step.

The original KLC-017 ticket also asked for `cache_control: {type:
ephemeral}` on the stable prompt prefix. The Anthropic dispatcher sends
one plain-text prompt to the Claude CLI via stdin
([!FACT src=core/skills/runner.py:182-187]); there are no structured
message blocks to attach `cache_control` to. Independent CLI
invocations also do not share a cache. So caching is not achievable
without a new structured transport.

KLC-016 telemetry falls back to `len(text)//4` when no provider `usage`
block is present ([!FACT src=core/skills/runner.py]). The stored numbers
do not record whether they are estimated or real, which can mislead the
`klc metrics --rollup` reader.

[!DECISION D-001] Split scope: deliver compressed cards + telemetry
honesty now; defer provider caching to a follow-up ticket gated on a
structured Anthropic transport.

## Acceptance Criteria

1. AC-1: `write_step_card()` does **not** embed `impl.md` by default;
   the step card references it by path with an explicit "read this role
   prompt before acting" instruction.
2. AC-2: An opt-in inline mode (`inline=True` / `KLC_CARD_INLINE=1`)
   still embeds `impl.md` for paste-only workflows. Both modes covered
   by tests.
3. AC-3: Token telemetry records a `source` field per phase:
   `"provider"` when parsed from a real `usage` block, `"estimated"`
   when derived from `len//4`. `cache_hit` is non-zero only for
   `source=provider`.
4. AC-4: `klc metrics --rollup` surfaces the telemetry source and does
   not present estimated values as exact provider usage.
5. AC-5: Before/after step-card byte size recorded for at least one
   build-step fixture (proves the guaranteed size reduction).
6. AC-6: `_PREAMBLE_TMPL` duplication trimmed opportunistically (no
   ticket info already in meta) — minor, non-blocking.

## Non-goals

- `cache_control: ephemeral` / provider prompt caching (deferred,
  blocked by transport — new ticket).
- Claiming "repeated build steps become nearly free" — not achievable
  with independent CLI calls.
- Reworking the runner transport to a structured Anthropic API.

## Affected modules

- `core/skills/artefacts.py`: `write_step_card()` (compressed/inline mode),
  `_PREAMBLE_TMPL` trim — src=core/skills/artefacts.py:226,103
- `core/templates/impl-step.md.j2`: role-prompt section becomes a
  reference by default — src=core/templates/impl-step.md.j2
- `core/skills/runner.py`: telemetry `source` marker — src=core/skills/runner.py
- `core/skills/metrics.py`: rollup surfaces source — src=core/skills/metrics.py
- `tests/integration/`: new test for compressed vs inline card + size delta
- `docs/process.md`: document compressed-card default + telemetry source

## Open questions

None blocking. Inline mode default is **off** (compressed by default),
since klc cards already assume a filesystem-capable agent (Navigation
section points at `.klc/index/*.json` + LSP).

## Estimate

- complexity: 1 (localized, well-understood edits)
- uncertainty: 1 (telemetry source wiring needs care)
- risk: 0 (no user-facing or data impact)
- manual: 0 (covered by tests)
- total: 2 → **S-track**
