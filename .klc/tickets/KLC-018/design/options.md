---
ticket: KLC-018
phase: design
authority: agent
---

# KLC-018 — Design

One option only — there are no architectural alternatives for this
remediation work. Each block is a targeted fix to a specific defect.

## Option A — targeted fixes per block (CHOSEN)

### [A] KLC-013 restore strategy

Port via cherry-pick, not raw branch merge. `feature/KLC-013-discovery-lite`
diverged before KLC-014/016 touched the same files (`phases.yml`,
`models.yml`, `phase_completion.py`, `runner.py`). Cherry-picking commit
`277f2b7` and resolving conflicts file-by-file is cleanest.

Changes:
- `config/phases.yml`: intake gains 3 picks (`confirm-route`,
  `force-full-discovery`, `force-xs-skip`); add `discovery-lite` for
  `[XS,S]`; restrict `discovery` to `[M,L]`.
- `core/skills/route_heuristic.py`: port verbatim from `277f2b7`.
- `core/phases/intake.py`: add `_classify_route` + set `route_hint`,
  `route_signals`, `track` in meta.
- `config/models.yml`: add `discovery-lite: coding`; per_track.XS.
  `discovery-lite: local-simple`.
- **AC-A3 guard** (new): in `ack.py`, before `apply_ack`, when
  `phase_id == "intake"` and `pick_id == 3` (force-xs-skip), check
  `meta.route_hint`. If absent or not "XS" → error and abort.
- **AC-A4** (new): in `phase_completion.py::can_complete_discovery_lite`,
  add: (1) `estimate.total ≤ 2` for XS, `≤ 5` for S; (2)
  `len(affected_modules) >= 1`.
- **AC-A5**: replace `models.resolve("indexing")` in runner.py Ollama
  fallback with `models.resolve_role("local-coding")` — direct role
  lookup, no coupling to pseudo-phase.

### [B] KLC-015 cascade wiring

Insert `review_cascade.decide()` in `scripts/review.py` at line ~904,
immediately after `always, conditional = _load_reviewers()` and before
the `for r in active` loop. When `use_full_review == False`, replace
`active` with a single cheap-reviewer stub.

Cheap reviewer: a synthetic reviewer entry pointing to a new agent
`core/agents/review/cheap.md` (focused diff, peripheral-only scope).
Model: `review-cheap` role from `models.yml`.

**AC-B2 fail-closed** in `review_cascade.py::decide()`:
- Empty `file_tiers` after classifier call → return
  `CascadeDecision(use_full_review=True, reason="classifier returned no files")`
- `skipped_scope` (scope comparison unavailable) → same.

### [C] KLC-016 telemetry envelope split

`_dispatch_anthropic` with `--output-format json` returns a JSON envelope:
```json
{"type": "result", "result": "<markdown>", "usage": {...}}
```
Split in `run_agent()`:
1. Try `json.loads(stdout)` — if succeeds and has `result` key, write
   `payload["result"]` to `out_path` (the markdown text); parse
   `payload.get("usage")` for telemetry.
2. If parse fails or no `result` key → fall back to writing `stdout`
   as-is (backward compat).

Then enable `--output-format json` as default by appending it to
`CLAUDE_ARGS` default: `"--print --output-format json"`.

OpenAI (AC-C3): `_dispatch_openai` already has the response dict; extract
`response["usage"]` and return it as 4th element of the tuple, or pass
via a wrapper to `_write_token_metrics`.

### [D] KLC-012 scope_delta holes

**AC-D1 unknown files**: in `scope_delta.compare()`, after
`_files_to_modules()`, collect files that matched NO module prefix into
`unknown_files`. Return as new key. In `ack.py` guard: treat non-empty
`unknown_files` as expansion.

**AC-D2 skipped=hard-fail**: in `ack.py` guard for `review`/`integrate`,
when `delta.get("skipped")` is set → write `[!CONFLICT]` and return 1
(currently skipped → silently passes through via the
`not delta.get("skipped")` check).

### [E] KLC-014 condition validation

**AC-E1**: add `validate_condition_syntax(phases_path)` in
`validate_config.py`. Iterate all phases, extract `condition:` field if
present, call `_eval_condition(expr, {})` — if it returns True due to
fallback (unknown expression), emit warning. The distinguishing signal:
if the expression does NOT match any known pattern in `_eval_condition`
(none of the regexes match), it's unrecognised. Extract a
`_is_known_condition(expr)` helper from `phases.py` for this.

**AC-E2**: in `phase_completion.py::_sync_risk_tags`, if `spec.md` has
frontmatter but `risk_tags` key is entirely absent (not just empty),
return a completion error rather than silently leaving meta without it.

## impl-plan structure

7 steps, roughly independent per block:

| Step | Block | Files |
|------|-------|-------|
| 1 | A: phases.yml + models.yml | `config/phases.yml`, `config/models.yml` |
| 2 | A: route_heuristic + intake | `core/skills/route_heuristic.py`, `core/phases/intake.py` |
| 3 | A: ack guard + phase_completion + runner fallback | `core/phases/ack.py`, `core/skills/phase_completion.py`, `core/skills/runner.py` |
| 4 | B: cascade wiring + fail-closed + cheap agent | `scripts/review.py`, `core/skills/review_cascade.py`, `core/agents/review/cheap.md` |
| 5 | C: envelope split + json default + OpenAI usage | `core/skills/runner.py` |
| 6 | D: scope_delta unknown bucket + skipped hard-fail | `core/skills/scope_delta.py`, `core/phases/ack.py` |
| 7 | E: condition validation + risk_tags completion | `core/skills/validate_config.py`, `core/skills/phases.py`, `core/skills/phase_completion.py` |

[!DECISION D-001] Port KLC-013 via cherry-pick + conflict resolution (not branch merge).
[!DECISION D-002] Cheap reviewer = new `core/agents/review/cheap.md` stub invoked via existing job-card machinery, not a code bypass.
[!DECISION D-003] Ollama fallback uses `resolve_role("local-coding")` directly — requires adding `resolve_role` to `models.py` API.
[!DECISION D-004] JSON-mode backward compat: if `json.loads` fails or no `result` key, write stdout as-is. Zero risk to existing runs.
