---
ticket: KLC-052
authority: hybrid
last_generated: 2026-06-26T00:00:00Z
---

# Test plan — KLC-052

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | e2e | tests/e2e/test_orchestrator.py::test_run_skill_resolves_phase_via_klc_status | `/klc:run <KEY>` calls `klc status`, derives current phase; does not fabricate output |
| AC-2 | acceptance | tests/integration/test_orchestrator_dispatch.py::test_xs_phase_runs_inline | XS-track phase executes inline (no Task subagent); confirmed by absence of Task tool call |
| AC-2 | acceptance | tests/integration/test_orchestrator_dispatch.py::test_ml_phase_dispatches_subagent | M-track phase dispatches `klc-<phase>` subagent via Task tool; confirmed by Task call |
| AC-2 | acceptance | tests/integration/test_orchestrator_dispatch.py::test_dispatch_decision_derives_from_meta_and_phases_yml | XS/M-L decision comes only from `meta.json:track` + `phases.yml:tracks`; no hand-kept map |
| AC-3 | acceptance | tests/integration/test_orchestrator_signal.py::test_structured_signal_parsed_correctly | Orchestrator parses `{phase, signal, artifacts[], blocking_questions[], next_action}` from subagent output |
| AC-3 | acceptance | tests/integration/test_orchestrator_signal.py::test_orchestrator_does_not_reread_phase_artifacts | After a clean signal, orchestrator does not open any artifact files (context stays small) |
| AC-4 | acceptance | tests/integration/test_orchestrator_run_to_gate.py::test_ack_auto_then_next_after_done | After phase reports done, orchestrator calls `klc ack --auto` then `klc next`; no new throttle invented |
| AC-4 | acceptance | tests/integration/test_orchestrator_run_to_gate.py::test_reuses_kl045_gate_policy_not_custom | Gate decisions come from `gate_policy.evaluate` (KLC-045); orchestrator adds no separate evaluation logic |
| AC-5 | acceptance | tests/integration/test_orchestrator_stop.py::test_stops_when_ack_auto_declines | When `ack --auto` returns `pick_required` / gate dirty / ambiguous pick, loop halts and surfaces to human |
| AC-5 | acceptance | tests/integration/test_orchestrator_stop.py::test_stops_when_blocking_questions_nonempty | When structured signal has non-empty `blocking_questions[]`, loop halts before calling `ack --auto` |
| AC-5 | acceptance | tests/integration/test_orchestrator_stop.py::test_stops_at_interactive_clarify_gate | Clarify phase (AC-11 coupling) causes loop to halt; not auto-advanced |
| AC-6 | acceptance | tests/integration/test_orchestrator_failure.py::test_retries_once_on_bad_signal | Garbage/unparseable signal triggers exactly one retry of the same phase |
| AC-6 | acceptance | tests/integration/test_orchestrator_failure.py::test_stops_after_two_consecutive_failures | Second consecutive failure (or timeout) causes loop to STOP and surface error; does not advance |
| AC-6 | acceptance | tests/integration/test_orchestrator_failure.py::test_no_silent_skip_on_failure | Failed phase is surfaced to human — not silently skipped or auto-advanced past |
| AC-7 | acceptance | tests/integration/test_clarify_gate.py::test_low_confidence_always_fires_gate | `route_confidence == "low"` → clarify pass fires unconditionally after intake |
| AC-7 | acceptance | tests/integration/test_clarify_gate.py::test_high_confidence_gate_does_not_fire | `route_confidence == "high"` → no clarify pass; proceeds to discovery directly |
| AC-7 | acceptance | tests/integration/test_clarify_gate.py::test_gate_fires_without_requiring_user_content | Gate triggers regardless of whether `raw.md` is empty or sparse; does not pre-screen content |
| AC-8 | acceptance | tests/integration/test_clarify_gate.py::test_ask_user_question_called_in_main_loop | Clarify pass issues a single `AskUserQuestion` with 2–4 questions; no background subagent path |
| AC-8 | acceptance | tests/integration/test_clarify_gate.py::test_clarify_batches_2_to_4_questions | Single `AskUserQuestion` carries between 2 and 4 design-changing questions |
| AC-9 | acceptance | tests/integration/test_clarify_gate.py::test_answers_written_back_to_raw_md | Clarify answers are appended/merged into `raw.md` before re-routing |
| AC-9 | acceptance | tests/integration/test_clarify_gate.py::test_route_recomputed_after_clarify | `route_heuristic` is re-run after write-back; `meta.json` reflects new route |
| AC-9 | acceptance | tests/integration/test_clarify_gate.py::test_intake_triage_machinery_reused | Clarify pass delegates to `core/agents/intake-triage.md`; no duplicate enrichment logic |
| AC-10 | acceptance | tests/integration/test_clarify_gate.py::test_nothing_to_add_satisfies_gate | User answering "nothing to add" clears the gate; ticket proceeds to discovery |
| AC-10 | acceptance | tests/integration/test_clarify_gate.py::test_gate_is_mandatory_not_content_mandatory | Gate always fires on low confidence even if user produces no new content |
| AC-11 | acceptance | tests/integration/test_orchestrator_stop.py::test_loop_stops_at_clarify_because_interactive | Orchestrator loop stops before dispatching discovery-clarify; clarify is a human-interaction phase |
| AC-11 | e2e | tests/e2e/test_discovery_split.py::test_discovery_split_clarify_then_author | Discovery runs as two steps: clarify (main-loop, interactive) then author (background subagent, synthesis) |
| AC-12 | acceptance | tests/integration/test_clarify_style.py::test_batch_style_uses_ask_user_question | `clarify.style: batch` → single `AskUserQuestion` with all questions bundled |
| AC-12 | acceptance | tests/integration/test_clarify_style.py::test_serial_style_asks_one_question_at_a_time | `clarify.style: serial` → one question per prompt exchange (superpowers-style prose) |
| AC-12 | acceptance | tests/integration/test_clarify_style.py::test_batch_is_default_style | Omitting `clarify.style` from config defaults to `batch` behavior |
| AC-12 | acceptance | tests/integration/test_clarify_style.py::test_style_is_global_no_per_track_override | Per-track `clarify.style` override has no effect; config key is global-only |
| AC-12 | acceptance | tests/integration/test_clarify_style.py::test_style_ignored_on_headless_runner_path | `runner.py` headless path parks at clarify; `clarify.style` is not consulted |
| AC-12 | acceptance | tests/integration/test_clarify_style.py::test_style_ignored_on_manual_cli_path | Manual-CLI path (`human edits raw.md`) proceeds without reading `clarify.style` |

## Edge cases

- **Garbage signal mid-loop**: subagent returns JSON with missing required keys (e.g. no `signal` field) — orchestrator must treat this as an unparseable signal and retry, not advance.
- **Timeout on retry**: first attempt times out, retry also times out — orchestrator stops and surfaces both timeouts; does not silently continue.
- **`blocking_questions[]` with empty strings**: treat as empty (gate does not fire on blank entries); only genuinely populated arrays should halt the loop.
- **`ack --auto` returns `pick_required`**: multiple competing picks exist — orchestrator surfaces to human rather than picking arbitrarily.
- **Low confidence + user answers "nothing to add" twice**: second gate invocation after re-route (if confidence remains low) must re-fire correctly — not skip.
- **`clarify.style` set to an unknown value**: reject at config load time (fail-closed); do not silently fall back to `batch` without a visible warning.
- **XS phase on M-track ticket**: if a phase's `tracks:` block includes both XS and M, dispatch decision follows `meta.json:track` (M → subagent), not the phase's XS membership.
- **Runner.py encounters an interactive clarify phase**: must park, not attempt to execute; parking must be recorded in `meta.json` or surfaced as a log entry.
- **Structured signal with `next_action` pointing to a non-existent phase**: orchestrator rejects and surfaces as a failure — does not attempt to jump to an unknown phase.

## Regression scenarios

- **`klc-plugin/skills/` thin-adapter invariant** (C-001): after this ticket, no plugin skill should contain inline orchestration logic that duplicates `klc` CLI logic — verify `run/SKILL.md` derives all decisions from `phases.yml` and `meta.json`.
- **Model pinning unchanged** (C-002): the generated `klc-<phase>` subagents must still carry correct `model:` frontmatter from `models.yml`; `plugin_gen.py` output must not regress.
- **`ack --auto` gate-policy unmodified** (C-003): existing `tests/integration/test_gate_policy.py` suite must pass unchanged — KLC-045 logic must not be altered by this ticket.
- **`intake-triage.md` correctness** (existing): mandatory clarify reusing `intake-triage.md` machinery must not regress the existing intake routing tests in `tests/test_intake_routing.py`.
- **`runner.py` headless never executes interactive phases** (C-005): existing headless CI path must still complete non-interactive tracks end-to-end via `tests/e2e_pipeline.py`.
- **`route_heuristic` confidence output shape** (existing): `tests/test_route_heuristic_confidence.py` must pass; confidence field shape must not change.
- **Discovery no longer runs as a monolithic subagent** (AC-11): if any existing fixture or test assumes discovery is a single background call, update it — the split into clarify + author changes the observable call sequence.

## Detailed coverage
<!-- TBD — populated in phase 4 after Design -->

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
