---
ticket: KLC-018
phase: build
authority: agent
---

# KLC-018 build log

## Step 1 — phases.yml + models.yml (Block A)

**Outcome**: green

- `phases.yml`: intake picks 1=confirm-route/2=force-full-discovery/3=force-xs-skip
  (pick_required=true); `discovery-lite` phase added for [XS,S]; `discovery`
  restricted to [M,L]
- `models.yml`: `discovery-lite: coding`; `per_track.XS.discovery-lite: local-simple`
- Verified: XS track = [intake, discovery-lite, xs-build, ...]; M track = [..., discovery, ...]

## Step 2 — route_heuristic + intake.py (Block A)

**Outcome**: green

- `route_heuristic.py` ported verbatim from commit 277f2b7; verified classify("fix typo", bug) → XS
- `intake.py`: `_classify_route()` added; meta gets `route_hint`, `route_signals`, `track`
- INTAKE_OK output shows route and pick hints

## Step 3 — ack guard + phase_completion + runner fallback (Block A)

**Outcome**: green

- `ack.py`: force-xs-skip guard — pick 3 on intake blocked if `route_hint != "XS"`
- `phase_completion.py`: `can_complete_discovery_lite()` — new full checker:
  spec sections, checklist items, risk_tags in frontmatter, estimate.total vs track,
  affected_modules ≥ 1
- `models.py`: `resolve_role(role_name)` added — direct role lookup without phase coupling
- `runner.py` Ollama fallback: uses `resolve_role("local-coding")` instead of `resolve("indexing")`
- `tests/e2e_pipeline.py`: intake ack uses pick=1; discovery-lite fixture added;
  seed_ticket adds route_hint; minimal modules.json in scratch
- `tests/fixtures/discovery.md`: AC items use `- [ ]` format; risk_tags in frontmatter
- All 4 tracks pass e2e

## Step 4 — cascade wiring + fail-closed + cheap agent (Block B)

**Outcome**: green

- `review_cascade.py`: fail-closed — empty `file_tiers` → full review;
  `skipped` scope → full review (removed from previous permissive path)
- `core/agents/review/cheap.md`: new minimal reviewer for peripheral diffs
- `scripts/review.py`: cascade wired at line ~904; when `use_full_review=False`
  replaces active reviewers with cheap agent
- 2 new integration tests: empty_tiers and skipped_scope both → full review
- Fixed existing cascade tests: removed `skipped` from peripheral mock

## Step 5 — telemetry envelope split + json default + OpenAI (Block C)

**Outcome**: green

- `runner.py`: envelope split — `json.loads(stdout)` → write `payload["result"]` only;
  fallback to raw stdout if no `result` key
- `runner.py`: `CLAUDE_ARGS` default changed from `"--print"` to
  `"--print --output-format json"`
- `_dispatch_openai`: wraps response in envelope with usage when present;
  `_parse_usage_from_output` extracts provider token counts

## Step 6 — scope_delta unknown bucket + skipped hard-fail (Block D)

**Outcome**: green

- `scope_delta.py`: `_files_to_modules` returns `(modules, unknown_files)`;
  `compare()` adds `unknown_files` key; `expansion` includes unknown files
- `ack.py`: unknown_files counted as expansion; `skipped` for review-only phases
  with `modules.json` in reason → hard fail; `no changed files` → warn only
- `_SCOPE_HARD_FAIL_PHASES = {"review"}` (not integrate — checklist, no irreversible work)
- e2e: minimal modules.json in scratch; all tracks pass

## Step 7 — condition validation + risk_tags completion (Block E)

**Outcome**: green

- `phases.py`: `_is_known_condition(expr)` — static pattern matcher
- `validate_config.py`: `validate_condition_syntax()` added; called in `validate_all()`
- `phase_completion.py::can_complete_discovery_lite`: validates `risk_tags` key
  present in frontmatter (empty `[]` is valid)
- `docs/process.md`: phase table updated (discovery-lite, intake picks), XS fast-track
  section updated, cascade fail-closed documented, scope guard explained

**All tests green**: DOCTOR_OK, smoke OK, e2e 4 tracks + negative + conditional,
cascade integration (6 tests), token telemetry integration (6 tests).
