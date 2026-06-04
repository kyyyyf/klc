---
ticket: KLC-018
kind: bug
authority: agent
---

# KLC-018 — Detailed test plan

## Acceptance coverage

### Step 1 — phases.yml + models.yml (Block A)

| # | Test | How |
|---|------|-----|
| 1.1 | `phases.yml` loads without error after changes | `python3 -c "import sys; sys.path.insert(0,'core/skills'); import phases; phases.load_phases(force=True)"` |
| 1.2 | XS track uses `discovery-lite`, not `discovery` | `track_phases("XS")` → `discovery-lite` present, `discovery` absent |
| 1.3 | M/L track uses `discovery`, not `discovery-lite` | `track_phases("M")` → `discovery` present, `discovery-lite` absent |
| 1.4 | S track uses `discovery-lite` | `track_phases("S")` → `discovery-lite` present |
| 1.5 | intake has 3 picks and is `pick_required: true` | `ph.by_id("intake").picks` has 3 entries; `pick_required=True` |
| 1.6 | `models.yml` has `discovery-lite: coding` | load_models(); assert role exists |
| 1.7 | `per_track.XS.discovery-lite == local-simple` | models.resolve("discovery-lite", track="XS").model == haiku |
| 1.8 | `klc doctor` passes | `python3 core/phases/doctor.py` → DOCTOR_OK |

### Step 2 — route_heuristic + intake.py (Block A)

| # | Test | How |
|---|------|-----|
| 2.1 | classify bug "fix typo" → XS | `route_heuristic.classify("fix typo", kind="bug").hint == "XS"` |
| 2.2 | classify feature with migration keyword → M | `route_heuristic.classify("database migration for auth", kind="feature").hint == "M"` |
| 2.3 | classify with ≥3 module names → M | pass text with 3+ known module names → hint >= "M" |
| 2.4 | intake sets route_hint in meta.json | `klc intake TEST-XXX --kind bug "fix typo"` → meta.json has `route_hint`, `route_signals`, `track` |
| 2.5 | intake prints route info | stdout of `klc intake` contains "route=" |

### Step 3 — ack guard + phase_completion + runner fallback (Block A)

| # | Test | How |
|---|------|-----|
| 3.1 | force-xs-skip blocked for route_hint=S | create ticket with route_hint="S" at intake:ack-needed; `klc ack --pick 3` → exit 1, error message |
| 3.2 | force-xs-skip blocked when route_hint absent | meta without route_hint; `klc ack --pick 3` → exit 1 |
| 3.3 | force-xs-skip allowed for route_hint=XS | meta with route_hint="XS"; `klc ack --pick 3` → advances to xs-build:work |
| 3.4 | discovery-lite rejects total>2 for XS | meta track=XS, estimate.total=3, spec valid → `can_complete_discovery_lite()` returns False |
| 3.5 | discovery-lite rejects total>5 for S | meta track=S, estimate.total=6 → False |
| 3.6 | discovery-lite rejects empty affected_modules | meta.affected_modules=[], estimate valid → False |
| 3.7 | discovery-lite passes with valid data | track=XS, total=2, affected_modules=["mod"] → True |
| 3.8 | Ollama fallback uses local-coding role | mock ollama absent; fallback resolves to Haiku (not via indexing phase) |
| 3.9 | e2e XS track passes end-to-end | `python3 tests/e2e_pipeline.py --track XS` → SUCCESS |
| 3.10 | e2e S track passes end-to-end | `python3 tests/e2e_pipeline.py --track S` → SUCCESS |

### Step 4 — cascade wiring + fail-closed + cheap agent (Block B)

| # | Test | How |
|---|------|-----|
| 4.1 | empty file_tiers → full review | mock _get_file_tiers returning {}; `decide()` → use_full_review=True |
| 4.2 | skipped scope → full review | mock scope_delta skipped=True; `decide()` → use_full_review=True |
| 4.3 | peripheral diff → cheap review via review.py | mock cascade decision; review.py launches only cheap reviewer |
| 4.4 | cascade.enabled=false → full pipeline | cascade config disabled; review.py launches all reviewers |
| 4.5 | cascade.enabled=true, critical tier → full pipeline | mock tier=critical; review.py launches full pipeline |
| 4.6 | cheap.md exists and is readable | `Path("core/agents/review/cheap.md").exists()` → True |
| 4.7 | test_review_cascade.py all pass | `python3 tests/integration/test_review_cascade.py` |

### Step 5 — envelope split + json default + OpenAI (Block C)

| # | Test | How |
|---|------|-----|
| 5.1 | JSON envelope → only result text in artifact | mock dispatcher returning JSON envelope; out_path contains only `result` value |
| 5.2 | JSON envelope → usage extracted as provider | meta.json source="provider", real token counts |
| 5.3 | plain text stdout → written as-is | mock returning plain markdown; out_path == stdout |
| 5.4 | anthropic default args include `--output-format json` | inspect `_dispatch_anthropic` argv construction |
| 5.5 | OpenAI usage persisted | mock openai response with usage; meta.json has provider token counts |
| 5.6 | test_token_telemetry.py all pass | `python3 tests/integration/test_token_telemetry.py` |

### Step 6 — scope_delta unknown bucket + skipped hard-fail (Block D)

| # | Test | How |
|---|------|-----|
| 6.1 | file outside modules.json prefixes → unknown_files | `scope_delta.compare()` with file not in any module → result["unknown_files"] non-empty |
| 6.2 | unknown files count as expansion in ack guard | create ticket, diff touches unknown file; `klc ack review` → blocked |
| 6.3 | skipped scope on review:ack-needed → blocked | modules.json absent; `klc ack review` → exit 1, [!CONFLICT] written |
| 6.4 | skipped scope on non-guarded phase → not blocked | modules.json absent; `klc ack learn` → passes |
| 6.5 | e2e --negative tests still pass | `python3 tests/e2e_pipeline.py --negative` |

### Step 7 — condition validation + risk_tags completion (Block E)

| # | Test | How |
|---|------|-----|
| 7.1 | typo in condition → doctor warning | synthetic phases.yml with `condition: "meta.risk_tgs in ['x']"`; `validate_config.validate_all()` → warning |
| 7.2 | valid condition → no warning | `condition: "meta.risk_tags in ['security']"` → no warning |
| 7.3 | no condition field → no warning | phase without condition → no warning |
| 7.4 | `_eval_condition` unknown expr still returns True | `_eval_condition("meta.nonexistent_op value", {})` → True |
| 7.5 | spec without risk_tags key → completion fails | spec.md without `risk_tags:` line; `can_complete_discovery_lite()` → False |
| 7.6 | spec with `risk_tags: []` → completion passes | empty list is valid |
| 7.7 | spec with `risk_tags: [security]` → completion passes | non-empty valid list |
| 7.8 | full e2e all tracks | `python3 tests/e2e_pipeline.py` → ALL PASSED |
| 7.9 | doctor clean | `python3 core/phases/doctor.py` → DOCTOR_OK |

## Edge cases

| # | Scenario | Expected |
|---|----------|----------|
| E-1 | `force-xs-skip` pick with route_hint absent | blocked, same as non-XS |
| E-2 | discovery-lite ack on M-track ticket | blocked by can_complete_discovery_lite track check |
| E-3 | JSON envelope with no `result` key (unusual format) | fall back to writing stdout as-is |
| E-4 | Empty diff in scope_delta | returns skipped="no changed files"; hard-fail only on guarded phases |
| E-5 | condition syntax valid but field doesn't exist at runtime | runtime returns True (fail-open); static validation passes (syntax is known) |
| E-6 | Cheap reviewer job card written but agent not dispatched (offline mode) | works the same as normal offline mode — human fulfils card |
