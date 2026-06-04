# KLC-017 suggestions

## Summary

KLC-017 is useful, but the current intake wording mixes two different goals:

- compressed prompt cards, which are straightforward and low-risk;
- provider prompt caching, which depends on the actual Anthropic transport and cannot be assumed from markdown prompt generation alone.

The safer scope is to implement compressed cards first, then add prompt caching only after the runner can prove real cache usage from provider telemetry.

## Findings

### High: read-once references can break copy-paste workflows

`write_step_card()` currently embeds `core/agents/impl.md` into each build step card via `impl_prompt`. Replacing that with only a path reference is safe for local agents with filesystem access, but unsafe for external copy-paste workflows where the model cannot read files.

Recommendation:

- support a local-agent mode where the card links to `core/agents/impl.md`;
- keep an inline/export mode for paste-only workflows;
- make the card explicitly say that the role prompt must be read before acting.

### High: cache_control requires a real structured transport

The current Anthropic path in `runner.py` sends a single plain-text prompt to the Claude CLI through stdin. `cache_control: {type: ephemeral}` usually requires structured API/message blocks, not just a markdown string.

Recommendation:

- do not make prompt caching an unconditional acceptance criterion;
- first confirm that the selected Anthropic transport supports cache control;
- if not, limit KLC-017 to prompt compression and measurement.

### Medium: telemetry may not prove real token savings

KLC-016 telemetry can fall back to estimated tokens using `len(text) // 4`. That is useful as a size proxy, but it is not the same as provider billing or cache behavior.

Recommendation:

- report whether each measurement is provider usage or estimated;
- compare before/after prompt size in bytes and estimated tokens;
- treat `cache_hit` as valid only when parsed from real provider usage.

### Medium: repeated build steps will not become nearly free automatically

Deleting the embedded `impl.md` from each step card reduces prompt size, but cache reuse depends on provider/session/request shape. Independent CLI invocations may not reuse cache unless the transport and request format support it.

Recommendation:

- claim prompt-size reduction as the guaranteed result;
- claim cache savings only after measured `cache_read_input_tokens` or equivalent provider telemetry.

### Low: preamble trimming is small ROI

Trimming `_PREAMBLE_TMPL` is fine, but it is minor compared with removing the repeated `impl.md` body from build step cards.

Recommendation:

- keep preamble cleanup as opportunistic;
- do not make it central to KLC-017 success.

## Proposed revised scope

### Phase A: compressed step cards

- Add local-agent step card mode that references `core/agents/impl.md` instead of embedding it.
- Preserve an inline/export mode for agents without filesystem access.
- Add tests for both modes.
- Measure before/after step card size.

### Phase B: telemetry validation

- Record before/after `bytes`, estimated tokens, and provider tokens when available.
- Mark telemetry source explicitly: `estimated` vs `provider`.
- Ensure `klc metrics --rollup` does not present estimated values as exact provider usage.

### Phase C: provider caching

- Implement Anthropic prompt caching only if the runner uses a transport that can send structured cache-control blocks.
- Parse and persist real cache-hit metrics.
- Add tests against representative provider output format.

## Acceptance criteria

- Step card can be generated in compressed mode and contains a path reference to `core/agents/impl.md`.
- Step card can still be generated in inline mode for copy-paste workflows.
- Tests cover compressed and inline step card generation.
- Before/after size reduction is recorded for at least one build step fixture.
- If cache savings are claimed, they are backed by real provider usage fields, not estimated token counts.

