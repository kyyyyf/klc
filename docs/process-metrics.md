# Process metrics

> **Note.** Capture points below named in terms of old phase-specific
> commands (`klc manual --continue`, `klc discover`, `klc integrate pre/post`,
> etc.) are historical. There are no such standalone verbs today — every
> transition is driven by the lifecycle verbs (`klc ack --pick N` / `klc next`,
> and their shortcuts). The metric names and semantics are unchanged; only the
> "Source / writer" labels reflect the earlier per-phase command shape.

Per-ticket metrics live in `.klc/tickets/<key>/meta.json:metrics`.
Rollups live in `.klc/knowledge/process-metrics.json`.

Skills:
- `core/skills/metrics.py set --ticket <k> --kv a=1 b=2` — merge
  values into `meta.json:metrics`.
- `core/skills/metrics.py show --ticket <k>` — print JSON.
- `core/skills/metrics.py rollup` — aggregate across all tickets,
  write rollup file.

`klc metrics <key>` and `klc metrics --rollup` are the front-end.

## Catalogue

Every phase writes a small, well-defined set of metrics. The learn
phase reads them all and computes derived values.

| Phase | Metric | Type | Source / writer |
|-------|--------|------|-----------------|
| 0 | `intake_ms` | int | `intake.py` timer |
| 0 | `intake_agent_ms` | int | intake-triage agent (only when triage runs) |
| 1 | `discovery_prep_ms` | int | `discover.py` pre-agent bundle |
| 1 | `discovery_ms` | int | discovery-agent total |
| 1 | `discovery_tokens` | int | discovery-agent self-report |
| 1 | `estimate_axes` | obj | `{complexity, uncertainty, risk, manual, total}` |
| 1 | `track` | str | XS/S/M/L (also a top-level meta field) |
| 2 | `test_plan_ms` | int | `test_plan.py` |
| 2 | `ac_count` | int | test-planner output |
| 3 | `design_ms` | int | design-agent |
| 3 | `options_count` | int | design-agent |
| 3 | `adr_triggered` | bool | `design.py --continue` |
| 4 | `build_ms` | int | verifier |
| 4 | `iterations` | int | how many red-fix iterations were used |
| 4 | `red_fixes` | int | `budget.py` counter |
| 4 | `mutation_score` | int (0-100) | test-writer / mutation tool |
| 4 | `build_head_sha` | str | `build.py --continue` |
| 5 | `review_ms` | int | review.py |
| 5 | `blocking` | int | review report aggregator |
| 5 | `non_blocking` | int | review report |
| 5 | `sub_agents_ran` | int | review report |
| 5 | `review_depth` | `cheap|lite|full` | review report frontmatter |
| 5 | `full_review_offered` | bool | review report frontmatter |
| 5 | `full_review_declined` | bool | review report frontmatter |
| 6 | `manual_minutes` | int | human input to `klc manual` |
| 6 | `manual_outcome` | `pass|fail` | `klc manual --outcome` |
| 7 | `integrate_pre_ms` | int | `integrate.py pre` |
| 7 | `merge_wait_ms` | int | `integrate.py post` (pre→post gap) |
| 7 | `merge_sha` | str | `integrate.py post` |
| 7 | `pre_post_snapshot_match` | bool | `integrate.py post` |
| 8 | `observe_hours` | float | `observe.py --now` or alert timestamp |
| 8 | `alerts_seen` | int | `observe.py --alert` |
| 9 | `cycle_time` | float (sec) | computed at learn: intake.started → learn.finished |
| 9 | `estimate_accuracy` | float | `actual_total / estimate.total` |
| 9 | `rework_count` | obj | sum of back-jumps per source phase |
| 9 | `token_spend` | obj | concatenated from agent-prompt footers |
| 9 | `cost_breakdown` | obj | see below |

### `cost_breakdown` (phase 9)

```json
{
  "tokens":  {"total": 42310, "by_agent": {"discovery": 5120, ...}},
  "lsp":     {"calls": 12},
  "api":     {"anthropic": 57, "openai": 0},
  "ci":      {"runs": 3, "minutes": 18},
  "rework":  {"build": 1, "review": 0}
}
```

Sources:

- `tokens.*` — per-phase token advisory (see `budget.py token_spend`
  handling) + agent-tail footer each prompt prints. `metrics.py`
  concatenates.
- `lsp.*` — agent-reported count of LSP tool calls (optional, advisory).
- `api.*` — populated only when a wrapper reports provider calls
  (external reviewer does). No pricing math.
- `ci.*` — populated when CI posts run data into
  `.klc/tickets/<key>/ci-runs.jsonl`. No-op without CI wiring.
- `rework.*` — sourced from `meta.rework_count` (a `{phase: count}` map), which
  `intake.py` initializes to `{}` and which `metrics.py` and the `learn`
  conditional gate read. The lifecycle engine increments it on every backward /
  rework transition (KLC-081): a needs-rework / request-changes ack pick that
  sends work back into an earlier phase, a backward `klc jump`, and `klc abort`.
  Each bumps `rework_count[phase]` for the phase whose work has to be redone (the
  re-entered phase for an ack pick or jump; the scrapped current phase for an
  abort). The ack path counts only genuine REWORK picks (`needs-rework`,
  `request-changes`, `regression`, `failed`, `revise-impl-plan`) — not the
  `learn` `extract-to-claudemd` self-loop, which is a legitimate second pass. The
  increment rides the transition's own state write, so it is durable and
  CAS-pushed feature-ON. A ticket with no backward moves keeps `rework_count
  == {}`, so `rework.*` is non-empty **iff** rework actually happened. Caveat:
  cross-track escalations (`upgrade-to-full`, `upgrade-to-S`) and the forward
  `observe` `rollback` → `learn` pick scrap or skip work but are treated as
  **route changes, not rework**, so `rework.*` intentionally does not count them.

## Rollup

`.klc/knowledge/process-metrics.json` is recomputed at every `klc
learn --continue` (and can be forced with `klc metrics --rollup`).
Shape:

```json
{
  "generated_at": "<ISO>",
  "tickets_total": N,
  "per_track": {
    "M": {
      "tickets": 12,
      "cycle_time_sec_median": 240000,
      "cycle_time_sec_p95":    720000,
      "rework_mean":           0.25,
      "cheap_escape_rate":     0.12
    }
  }
}
```

`cheap_escape_rate` — fraction of cheap/lite-reviewed tickets that later
had rework or regression. `null` when the track has no cheap/lite reviews.
A rising rate signals that the cascade is routing too aggressively to cheap
review for that module set; consider tightening tier classification or
adding sentinel patterns.

Retrospective agent (phase 9) reads the rollup to flag outliers
("this ticket's cycle time is 3× the track median"). If a single
lesson shows up in five retros in a row, that's a signal to promote
it from "note in retro" to a process rule in `docs/process.md`.
