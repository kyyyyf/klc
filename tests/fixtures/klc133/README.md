# KLC-133 headless envelope fixtures

usage-source: modelUsage
usage-evidence: the last `result` element's own `usage` covers only the parent's
last model call (`input_tokens` 10, `output_tokens` 59, `cache_read_input_tokens`
22075, `cache_creation_input_tokens` 496), while `modelUsage["claude-haiku-4-5-20251001"]`
sums to `inputTokens` 37, `outputTokens` 446, `cacheReadInputTokens` 61525,
`cacheCreationInputTokens` 15813, `costUSD` 0.03161175 — equal to that same
result's `total_cost_usd`. The `modelUsage` sum is strictly bigger on every
field, so `usage` alone misses tokens the run actually spent (the subagent's),
and the parser reads `modelUsage` instead.
subagent-messages: absent — every message in `envelope-verbose-subagent.json`
carries `parent_tool_use_id: null`; the subagent ran as a separate background
session (its own `agentId` and output file) rather than as an inline message
with a `parent_tool_use_id` back-reference. The one piece of first-hand
evidence that a subagent really ran is `subagent_stats.spawned: 1` on both
`result` elements, together with the doubled `modelUsage` totals against the
final turn's own `usage` (the comparison above).
claude-version: 2.1.285 (Claude Code)

- `envelope-single.json` — captured by the operator (impl-plan step-1, command 1);
  a single-turn, single JSON object envelope; identifiers redacted.
- `envelope-verbose-subagent.json` — captured by the operator (impl-plan step-1,
  command 2), `--output-format json --verbose`; a JSON array of 16 messages from
  a run that launched one background subagent (`Task`/`Agent` tool) and waited
  for its reply; identifiers redacted. **step-10 review-fix (AC-13, code-review
  MEDIUM + external MEDIUM):** the step-1 redaction script only scrubbed the
  top-level `session_id`/`uuid`/`parent_uuid`/`request_id`/`cwd` keys — it
  missed the free-text `tool_result` content embedded inside message bodies.
  Re-redacted to additionally scrub: every `/tmp/…` path (including the one
  embedded inside the `output_file:`/`outputFile` free text and the
  `tool_use_result.outputFile` key), the real subagent `agentId` (both the
  `tool_use_result.agentId` key and the `agentId: …` mention inside the
  free-text reply), every `msg_…` message id (both as a dict key under
  `wire_tool_inputs` and as an `"id"` value), every `toolu_…` tool-use id
  (both as a dict key and as an `"id"`/`tool_use_id"` value), every
  `thinking.signature` blob (replaced with a fixed placeholder — the key
  name `signature` itself is kept, only its value is sensitive), and any
  UUID pattern still present anywhere in a string (a session UUID had
  leaked into the free-text `output_file:` path even though the top-level
  `session_id` key was already redacted). No number, and no other
  structural key or value, was touched — `tests/integration/test_klc133_envelope_parser.py`'s
  literal-value tests, and every `num_turns`/`duration_ms`/`total_cost_usd`/
  `modelUsage` figure this ticket's Q-009 finding depends on, are unchanged.
- `envelope-multiturn-cache.json` — derived: the earlier of the two `type:
  "result"` elements in `envelope-verbose-subagent.json` (`result_index: 0`,
  `num_turns: 2`, `cache_read_input_tokens: 39450`,
  `cache_creation_input_tokens: 4072`), unchanged. See D-116 in
  `impl-plan.md`: the plan's derive snippet took the array's *last* `result`
  element, but that element's own `num_turns` is `1` (its turn count restarts
  at the async subagent-completion notification), so it does not exercise a
  multi-turn envelope on its own; the earlier element is a real captured
  `result` object with genuine multiple turns and non-zero cache reads and
  writes, so it stands in for the "multi-turn run with cache reads and cache
  writes" fixture instead.
- `envelope-is-error.json` — derived from `envelope-single.json`: `is_error`
  set to `true`, `subtype` set to `"error_during_execution"`, `result`
  replaced with `"(derived error run)"`; every other field unchanged.
