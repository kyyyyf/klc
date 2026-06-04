# KLC-018 impl-plan

## step-1 — phases.yml + models.yml (Block A)

Port intake picks and discovery-lite phase from commit `277f2b7`.

**Affected files**:
- `config/phases.yml`
- `config/models.yml`

**Changes**:
- `phases.yml` intake: add `pick_required: true`, picks 1=confirm-route
  (goto:next), 2=force-full-discovery (goto:discovery:work),
  3=force-xs-skip (goto:xs-build:work).
- `phases.yml`: add `discovery-lite` phase for `[XS, S]` before
  `discovery`; restrict `discovery` to `[M, L]`.
- `models.yml` phase_roles: add `discovery-lite: coding`.
- `models.yml` per_track.XS: add `discovery-lite: local-simple`.

**Expected tests**:
- `python3 -c "import sys; sys.path.insert(0,'core/skills'); import phases as ph; p=ph.load_phases(force=True); print([x.id for x in p.track_phases('XS')])"` → includes discovery-lite, not discovery
- `python3 core/phases/doctor.py` → DOCTOR_OK

**Rollback**: revert both config files

---

## step-2 — route_heuristic + intake.py (Block A)

**Affected files**:
- `core/skills/route_heuristic.py` (new — port from 277f2b7)
- `core/phases/intake.py`

**Changes**:
- Port `route_heuristic.py` verbatim; verify it imports cleanly.
- `intake.py`: add `_classify_route(desc, kind)` helper; call after
  creating meta.json; set `meta["route_hint"]`, `meta["route_signals"]`,
  `meta["track"]`; print route info in INTAKE_OK output.

**Expected tests**:
- `python3 -c "import sys; sys.path.insert(0,'core/skills'); import route_heuristic as r; print(r.classify('fix typo', kind='bug').hint)"` → "XS"

**Rollback**: delete route_heuristic.py; revert intake.py

---

## step-3 — ack guard + phase_completion + runner Ollama fallback (Block A)

**Affected files**:
- `core/phases/ack.py`
- `core/skills/phase_completion.py`
- `core/skills/runner.py`

**Changes**:
- `ack.py`: before `apply_ack`, when `pid == "intake"` and
  `args.pick == 3`, read `meta.route_hint`; if absent or != "XS",
  write error and return 1 (AC-A3).
- `phase_completion.py::can_complete_discovery_lite`: add check
  `estimate.total <= 2` for XS / `<= 5` for S (AC-A4); add check
  `len(meta.affected_modules) >= 1` (AC-A4).
- `runner.py::_dispatch_ollama` fallback: replace
  `models.resolve("indexing")` with direct role lookup. Add
  `resolve_role(role_name)` to `core/skills/models.py` API that
  returns a `ResolvedModel` for a named role; use
  `models.resolve_role("local-coding")` in fallback (AC-A5).

**Expected tests**:
- `python3 tests/e2e_pipeline.py --track XS` → PASS (uses discovery-lite)
- `python3 tests/e2e_pipeline.py --track S` → PASS
- Negative: ack KLC-018 intake --pick 3 when route_hint="S" → error

**Rollback**: revert ack.py, phase_completion.py, runner.py, models.py

---

## step-4 — cascade wiring + fail-closed + cheap agent (Block B)

**Affected files**:
- `scripts/review.py`
- `core/skills/review_cascade.py`
- `core/agents/review/cheap.md` (new)

**Changes**:
- `review_cascade.py::decide()`: fail-closed — empty `file_tiers` OR
  `skipped_scope` → `use_full_review=True` (AC-B2).
- `core/agents/review/cheap.md`: new minimal reviewer prompt for
  peripheral diffs (focused diff, no architecture/security depth).
- `review.py`: after `_load_reviewers()`, call
  `review_cascade.decide(ticket, diff_file)` when `cascade.enabled`.
  If `use_full_review=False`: replace `active` with cheap reviewer
  entry; log reason (AC-B1).

**Expected tests**:
- `python3 tests/integration/test_review_cascade.py` → PASS (updated)
- New test: `cascade_empty_tiers_forces_full_review`
- New test: `cascade_skipped_scope_forces_full_review`

**Rollback**: revert review.py, review_cascade.py; delete cheap.md

---

## step-5 — telemetry envelope split + json default + OpenAI usage (Block C)

**Affected files**:
- `core/skills/runner.py`

**Changes**:
- `run_agent()`: after `dispatcher()` call, before writing to `out_path`,
  try `json.loads(stdout)` — if success and `"result"` key present, write
  `payload["result"]` to `out_path` and extract `payload.get("usage")`.
  If parse fails → write `stdout` as-is (fallback, AC-C1).
- `_dispatch_anthropic`: change default `CLAUDE_ARGS` fallback from
  `"--print"` to `"--print --output-format json"` (AC-C2).
- `_dispatch_openai`: extract `response.get("usage", {})` and pass
  token counts to `_write_token_metrics` (AC-C3).

**Expected tests**:
- `python3 tests/integration/test_token_telemetry.py` → PASS (updated)
- New test: JSON envelope → only result text in artifact
- New test: plain text stdout → written as-is (backward compat)

**Rollback**: revert runner.py

---

## step-6 — scope_delta unknown bucket + skipped hard-fail (Block D)

**Affected files**:
- `core/skills/scope_delta.py`
- `core/phases/ack.py`

**Changes**:
- `scope_delta.py::compare()`: after `_files_to_modules`, compute
  `unknown_files = sorted(set(changed_files) - {f for m in modules for f...})`.
  Actually: collect files that matched no module prefix during
  `_files_to_modules`; add `unknown_files` key to return dict (AC-D1).
- `ack.py` scope guard: treat `len(delta.get("unknown_files", [])) > 0`
  as expansion (AC-D1). Change `skipped` check: when
  `delta.get("skipped") and pid in _SCOPE_GUARD_PHASES` → write
  `[!CONFLICT]` and return 1 (AC-D2).

**Expected tests**:
- New test: file outside module prefixes → `unknown_files` non-empty
- New test: `skipped` scope on review ack → blocked
- `python3 tests/e2e_pipeline.py --negative` → PASS

**Rollback**: revert scope_delta.py, ack.py

---

## step-7 — condition validation + risk_tags completion (Block E)

**Affected files**:
- `core/skills/validate_config.py`
- `core/skills/phases.py`
- `core/skills/phase_completion.py`

**Changes**:
- `phases.py`: extract `_is_known_condition(expr: str) -> bool` — returns
  True when `expr` matches at least one regex branch in `_eval_condition`
  (not just the fallback).
- `validate_config.py::validate_phase_roles()`: iterate phases, check
  `condition` field if present; call `_is_known_condition`; emit warning
  if unrecognised (AC-E1).
- `phase_completion.py::_sync_risk_tags`: if `risk_tags` key is
  completely absent from frontmatter (not just empty list), return
  completion failure "spec.md: missing risk_tags frontmatter field"
  (AC-E2). Empty `[]` still passes.

**Expected tests**:
- `python3 core/phases/doctor.py` on valid phases.yml → DOCTOR_OK
- New test: synthetic phases.yml with typo condition → warning in validate
- New test: spec without risk_tags key → completion fails
- `python3 tests/e2e_pipeline.py` all tracks → PASS

**Rollback**: revert all three files
