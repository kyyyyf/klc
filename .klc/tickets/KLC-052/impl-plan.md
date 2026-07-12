---
ticket: KLC-052
authority: hybrid
design_choice: option-A-minimal
last_generated: 2026-06-26T00:00:00Z
---

# Impl plan — KLC-052 (Option A: orchestrator skill + mandatory clarify gate)

Audience: test agent, impl agent, verifier, operator. Risky seam work
(the resolver + budget extraction that both executors depend on) goes
first, then the orchestrator loop, then Deliverable 2 (clarify gate +
config), then the prompt/docs wiring. Every step is one logical commit.

Test commands assume `PROJECT_ROOT=/home/ek/projects/klc` and run from
the repo root. Use `python3 -m pytest <path> -q`.

---

## step-1 — phase_resolver as single phase→agent source of truth
- **Goal**: Add `core/skills/phase_resolver.py` — the single
  `resolve_phase(ticket, phase_id) -> ResolvedPhase` that both executors
  will consume, derived only from `phases.yml` + `models.yml` + the
  generated `klc-plugin/agents/` set + `meta.json:track`.
- **RED**: write `tests/integration/test_orchestrator_dispatch.py::test_dispatch_decision_derives_from_meta_and_phases_yml` — assert an XS-track ticket on an XS-eligible phase yields `runs_inline=True` and an M-track ticket yields `runs_inline=False` with `agent_type == "klc-<phase>"`, using only `meta.track` + `phases.track_phases`. Cites test-plan AC-2 row 3.
- **GREEN**: implement `ResolvedPhase` dataclass + `resolve_phase` composing `phases.by_id(phase_id).prompt`, `load_models().resolve(phase_id, track=track).model`, `plugin_gen.cc_alias(model)`, existence of `klc-plugin/agents/{phase_id}.md`, and `runs_inline = track == "XS" and phase in phases.track_phases("XS")`. Also expose `cc_alias` publicly in `plugin_gen.py` (rename usage; keep `_cc_alias` as a thin alias for back-compat).
- **VERIFY**: `python3 -m pytest tests/integration/test_orchestrator_dispatch.py::test_dispatch_decision_derives_from_meta_and_phases_yml -q`
- **Expected**: `1 passed`
- **COMMIT**: `KLC-052 step-1: add phase_resolver.resolve_phase as the single phase→agent source of truth`
- **Affected files**: `core/skills/phase_resolver.py` (new), `core/skills/plugin_gen.py` (expose `cc_alias`), `tests/integration/test_orchestrator_dispatch.py` (new)
- **Interfaces**: `phase_resolver.resolve_phase`, `phase_resolver.ResolvedPhase`, `plugin_gen.cc_alias` — names only (signatures verified via LSP in build).
- **Depends on**: none
- **Code sketch**:
  ```python
  # core/skills/phase_resolver.py
  @dataclass
  class ResolvedPhase:
      phase_id: str; track: str; prompt_path: str | None
      model: str; cc_model: str; agent_type: str | None
      runs_inline: bool; interactive: bool

  def resolve_phase(ticket, phase_id):
      meta = lifecycle.read_meta(ticket); track = meta["track"]
      ph = phases.load_phases(); phase = ph.by_id(phase_id)
      model = models.load_models().resolve(phase_id, track=track).model
      agent_md = framework_root()/"klc-plugin"/"agents"/f"{phase_id}.md"
      runs_inline = track == "XS" and phase in ph.track_phases("XS")
      interactive = _is_interactive(meta, phase)   # clarify stamp + picks
      return ResolvedPhase(phase_id, track, phase.prompt or None, model,
          plugin_gen._cc_alias(model),  # step-1 also exposes public cc_alias
          f"klc-{phase_id}" if agent_md.exists() else None,
          runs_inline, interactive)
  ```

## step-2 — extract budget_guard from runner; advisory check_prompt_budget
- **Goal**: Extract budget + telemetry helpers from `runner.py` into
  `core/skills/budget_guard.py` (behavior preserved) and add
  `check_prompt_budget(track, estimated) -> BudgetVerdict`.
- **RED**: write `tests/test_budget_guard.py::test_hard_breach_is_flagged` and `::test_soft_breach_warns_not_blocks` — a `check_prompt_budget` over a hard-limit-exceeding estimate returns `verdict.hard_breach is True`; a soft-only breach returns `hard_breach is False, soft_breach is True`. (Negative test: gate bites on over-budget input.)
- **GREEN**: move `_load_budget_limits`/`_estimate_tokens`/`_write_token_metrics` into `budget_guard` as public `load_budget_limits`/`estimate_tokens`/`write_token_metrics`; add `check_prompt_budget`. Re-import them in `runner.py` (no behavior change there).
- **VERIFY**: `python3 -m pytest tests/test_budget_guard.py -q && python3 -m pytest tests/ -q -k runner`
- **Expected**: `2 passed` for the new file; existing runner tests still pass.
- **COMMIT**: `KLC-052 step-2: extract budget_guard from runner; add advisory check_prompt_budget`
- **Affected files**: `core/skills/budget_guard.py` (new), `core/skills/runner.py` (import the moved helpers), `tests/test_budget_guard.py` (new)
- **Interfaces**: `budget_guard.load_budget_limits`, `budget_guard.estimate_tokens`, `budget_guard.write_token_metrics`, `budget_guard.check_prompt_budget`, `budget_guard.BudgetVerdict`
- **Depends on**: none
- **Code sketch**:
  ```python
  # core/skills/budget_guard.py
  @dataclass
  class BudgetVerdict:
      hard_breach: bool; soft_breach: bool; estimated: int; limit: int | None
  def check_prompt_budget(track, estimated):
      soft, hard = load_budget_limits()
      h, s = hard.get(track), soft.get(track)
      return BudgetVerdict(bool(h and estimated > h),
                           bool(s and estimated > s), estimated, h)
  ```

## step-3 — runner.py consumes phase_resolver; parks on interactive (C-005)
- **Goal**: Make `runner.py` consume `phase_resolver` for prompt+model
  and PARK (never dispatch) on interactive phases — enforcing C-005.
- **RED**: write `tests/e2e/test_runner_parks_interactive.py::test_runner_parks_on_interactive_phase` — calling the headless run path on a phase resolved `interactive=True` writes a park marker (`meta.json:parked` or a `[!PARKED]` line) and returns a distinct non-zero rc; it does NOT invoke a provider dispatcher. (Fail-closed test: interactive input is refused, not silently executed.) Cites test-plan C-005 regression row + edge case "Runner.py encounters an interactive clarify phase".
- **GREEN**: in `run_agent`, resolve via `phase_resolver.resolve_phase`; if `interactive`, write the park marker and return the park rc before any dispatcher call. Use the resolved `prompt_path`/`model` instead of inline resolution.
- **VERIFY**: `python3 -m pytest tests/e2e/test_runner_parks_interactive.py -q && python3 -m pytest tests/e2e_pipeline.py -q`
- **Expected**: `1 passed`; the headless pipeline e2e still completes non-interactive tracks.
- **COMMIT**: `KLC-052 step-3: runner.py consumes phase_resolver and parks on interactive phases (C-005)`
- **Affected files**: `core/skills/runner.py`, `tests/e2e/test_runner_parks_interactive.py` (new)
- **Interfaces**: `runner.run_agent` (unchanged signature; internal park branch added) — none new.
- **Depends on**: step-1
- **Code sketch**:
  ```python
  resolved = phase_resolver.resolve_phase(ticket, phase_id) if ticket else None
  if resolved and resolved.interactive:
      _write_park_marker(ticket, phase_id, "interactive phase — headless parks (C-005)")
      return PARK_RC   # distinct non-zero, not a dispatch failure
  ```
- **Rollback note**: this changes the headless entry path; if the park
  branch misfires it could block non-interactive runs — guard the park
  strictly on `resolved.interactive` and keep the existing path otherwise.

## step-4 — stamp clarify_required on low-confidence intake
- **Goal**: Add the mandatory-clarify stamp in `intake.py`
  (`meta.json:clarify_required = true` when `route_confidence == "low"`).
- **RED**: write `tests/integration/test_clarify_gate.py::test_low_confidence_always_fires_gate`, `::test_high_confidence_gate_does_not_fire`, and `::test_gate_fires_without_requiring_user_content` — after intake, low confidence sets `clarify_required True` regardless of raw.md content; high confidence leaves it `False`/absent. (Negative + fail-closed: gate stamps unconditionally on low; never on high.) Cites test-plan AC-7 rows.
- **GREEN**: in `intake.run`, after computing `route`, set `meta["clarify_required"] = route["confidence"] == "low"`.
- **VERIFY**: `python3 -m pytest tests/integration/test_clarify_gate.py -q -k "fires or does_not_fire or without_requiring" && python3 -m pytest tests/test_intake_routing.py -q`
- **Expected**: `3 passed`; existing intake routing tests stay green.
- **COMMIT**: `KLC-052 step-4: stamp clarify_required on low-confidence intake`
- **Affected files**: `core/phases/intake.py`, `tests/integration/test_clarify_gate.py` (new)
- **Interfaces**: none (meta field add only)
- **Depends on**: none
- **Code sketch**:
  ```python
  route = _classify_route(desc, args.kind or "unknown")
  meta = { ..., "route_confidence": route["confidence"],
           "clarify_required": route["confidence"] == "low", ... }
  ```

## step-5 — clarify.yml + clarify_config.load_clarify_style
- **Goal**: Add `config/clarify.yml` + `core/skills/clarify_config.py`
  with fail-closed `load_clarify_style()`, global-only, default `batch`.
- **RED**: write `tests/integration/test_clarify_style.py::test_batch_is_default_style`, `::test_style_is_global_no_per_track_override`, and `::test_unknown_style_rejected_fail_closed` — absent config → `"batch"`; a per-track key is ignored; an unknown value raises a visible error (no silent fallback). (Negative + fail-closed.) Cites test-plan AC-12 rows + edge case "clarify.style set to an unknown value".
- **GREEN**: add `config/clarify.yml` (`clarify.style: batch`); implement `load_clarify_style()` reading project override then framework default (profile.yml pattern), validating value ∈ {batch, serial}, raising `ClarifyConfigError` otherwise.
- **VERIFY**: `python3 -m pytest tests/integration/test_clarify_style.py -q -k "default or global or unknown"`
- **Expected**: `3 passed`
- **COMMIT**: `KLC-052 step-5: add clarify.yml + clarify_config.load_clarify_style (fail-closed, global)`
- **Affected files**: `config/clarify.yml` (new), `core/skills/clarify_config.py` (new), `tests/integration/test_clarify_style.py` (new)
- **Interfaces**: `clarify_config.load_clarify_style`, `clarify_config.ClarifyConfigError`
- **Depends on**: none
- **Code sketch**:
  ```python
  _VALID = {"batch", "serial"}
  def load_clarify_style():
      style = _read_style() or "batch"          # project override → framework
      if style not in _VALID:
          raise ClarifyConfigError(f"clarify.style={style!r} invalid; use {_VALID}")
      return style
  ```

## step-6 — completion-signal contract + interactive clarify in agents
- **Goal**: Add the shared structured-completion-signal contract block to
  `core/agents/*.md` and the interactive clarify section to
  `core/agents/intake-triage.md`, then regenerate `klc-plugin/agents/`.
- **RED:** not applicable — prompt/agent-content + generated-artifact step; no runtime behavior is added in Python here. (Verification is the regen + frontmatter regression, below.)
- **GREEN**: append a shared "## Completion signal" block (the AC-3 JSON contract from design.md §3) to each `core/agents/*.md`; extend `intake-triage.md` with an interactive clarify section (one `AskUserQuestion`, 2–4 batched questions from `missing_info`, write-back to raw.md notes, re-route via `route_heuristic.classify`, clear `clarify_required`); run `python3 core/skills/plugin_gen.py`.
- **VERIFY**: `python3 core/skills/plugin_gen.py && python3 -m pytest tests/ -q -k plugin_gen`
- **Expected**: `Generated N agent files` line printed; plugin_gen tests pass (model frontmatter unchanged — C-002).
- **COMMIT**: `KLC-052 step-6: add completion-signal contract + interactive clarify to agents; regenerate plugin agents`
- **Affected files**: `core/agents/*.md` (shared block), `core/agents/intake-triage.md` (clarify section), `klc-plugin/agents/*.md` (regenerated)
- **Interfaces**: none (prompt content + generated files)
- **Depends on**: step-5

## step-7 — /klc:run orchestrator skill + run_signal parser
- **Goal**: Add `klc-plugin/skills/run/SKILL.md` (`/klc:run <KEY>`) — the
  orchestration loop: resolve via `phase_resolver`, route-aware dispatch,
  parse the structured signal, `ack --auto` + `next` throttle,
  retry-once-then-stop, stop at interactive/clarify gates and on
  blocking questions or budget hard-breach.
- **RED**: write `tests/e2e/test_orchestrator.py::test_run_skill_resolves_phase_via_klc_status` plus `tests/integration/test_orchestrator_signal.py::test_structured_signal_parsed_correctly`, `tests/integration/test_orchestrator_run_to_gate.py::test_ack_auto_then_next_after_done`, `tests/integration/test_orchestrator_stop.py::test_stops_when_blocking_questions_nonempty` + `::test_stops_at_interactive_clarify_gate`, and `tests/integration/test_orchestrator_failure.py::test_retries_once_on_bad_signal` + `::test_stops_after_two_consecutive_failures`. These assert the loop contract against the resolver/signal/ack-auto seams (no fabricated phase output; no artifact re-read on clean signal). Cites test-plan AC-1/AC-3/AC-4/AC-5/AC-6 rows.
- **GREEN**: write `run/SKILL.md` encoding the loop from design.md §3 and a small `core/skills/run_signal.py` helper (`parse_signal(text) -> Signal | None`) so the parse + retry decision is testable in Python (the SKILL.md calls it). The SKILL.md derives every decision from `klc status --json`, `phase_resolver`, and `ack --auto` — no inline orchestration logic duplicating klc CLI (C-001).
- **VERIFY**: `python3 -m pytest tests/e2e/test_orchestrator.py tests/integration/test_orchestrator_signal.py tests/integration/test_orchestrator_run_to_gate.py tests/integration/test_orchestrator_stop.py tests/integration/test_orchestrator_failure.py -q`
- **Expected**: `7 passed`
- **COMMIT**: `KLC-052 step-7: add /klc:run orchestrator skill + run_signal parser (route-aware, run-to-gate, retry-once)`
- **Affected files**: `klc-plugin/skills/run/SKILL.md` (new), `core/skills/run_signal.py` (new), `tests/e2e/test_orchestrator.py` (new), `tests/integration/test_orchestrator_signal.py` (new), `tests/integration/test_orchestrator_run_to_gate.py` (new), `tests/integration/test_orchestrator_stop.py` (new), `tests/integration/test_orchestrator_failure.py` (new)
- **Interfaces**: `run_signal.parse_signal`, `run_signal.Signal` — names only.
- **Depends on**: step-1, step-2, step-3, step-4, step-6
- **Code sketch**:
  ```python
  # core/skills/run_signal.py
  REQUIRED = ("phase", "signal", "artifacts", "blocking_questions", "next_action")
  def parse_signal(text, expected_phase):
      block = _last_json_fence(text)
      try: obj = json.loads(block)
      except Exception: return None                  # → retry (AC-6)
      if any(k not in obj for k in REQUIRED): return None
      if obj["phase"] != expected_phase: return None
      if obj["signal"] not in ("done","blocked","failed"): return None
      obj["blocking_questions"] = [q for q in obj["blocking_questions"] if q.strip()]
      return Signal(**{k: obj[k] for k in REQUIRED})
  ```

## step-8 — wire clarify.style + docs parity
- **Goal**: Wire the clarify-style + e2e discovery-split coverage and the
  docs parity (README execution surface, tracks proportionality rule).
- **RED**: write `tests/integration/test_clarify_style.py::test_batch_style_uses_ask_user_question`, `::test_serial_style_asks_one_question_at_a_time`, `::test_style_ignored_on_headless_runner_path`, `::test_style_ignored_on_manual_cli_path`, and `tests/e2e/test_discovery_split.py::test_discovery_split_clarify_then_author` + `tests/integration/test_clarify_gate.py::test_nothing_to_add_satisfies_gate`. These assert the style switch drives batch-vs-serial in the clarify path and that headless/manual paths never consult it. Cites remaining AC-8/AC-10/AC-11/AC-12 rows.
- **GREEN**: connect `clarify_config.load_clarify_style()` to the clarify section's question-issuing branch (batch=one AskUserQuestion / serial=one-at-a-time); confirm headless (`runner` parks) and manual-CLI paths take no `clarify_config` call. Update `klc-plugin/README.md` execution-surface table, `docs/process.md`, and `docs/tracks.md` (proportionality rule C-004).
- **VERIFY**: `python3 -m pytest tests/integration/test_clarify_style.py tests/e2e/test_discovery_split.py tests/integration/test_clarify_gate.py -q`
- **Expected**: `all passed` (the full clarify-gate + clarify-style + discovery-split suites green)
- **COMMIT**: `KLC-052 step-8: wire clarify.style into clarify path; docs parity for orchestrator + clarify gate`
- **Affected files**: `core/agents/intake-triage.md` (style branch), `klc-plugin/skills/run/SKILL.md` (style-aware clarify), `klc-plugin/README.md`, `docs/process.md`, `docs/tracks.md`, `tests/integration/test_clarify_style.py`, `tests/e2e/test_discovery_split.py`, `tests/integration/test_clarify_gate.py`
- **Interfaces**: none new
- **Depends on**: step-5, step-6, step-7

---

## YAGNI / self-review notes

- 8 steps: above the 3–7 ideal, but the feature is two coupled
  deliverables across `core/skills`, `core/phases`, `core/agents`,
  `config`, and `klc-plugin`. Steps were split honestly by one-commit /
  one-RED boundaries, not padded. The risky shared seam (resolver +
  budget extraction + runner park) is steps 1–3, first.
- Dependencies are linear and only reference earlier step ids.
- Every behaviour-changing step has a RED test at a public entry point
  and a VERIFY command; step-6 is the only `RED: not applicable` step
  (prompt-content + regeneration, verified by the plugin_gen regression).
- Gate/validator ACs carry negative + fail-closed tests: clarify stamp
  (step-4: fires on low / never on high / content-independent), clarify
  config (step-5: unknown value rejected, default batch), runner park
  (step-3: interactive refused, not executed), budget (step-2: hard
  breach flagged).
- No new external dependency (PyYAML already in use). New files are
  genuinely new components (one per step is the norm; step-7 adds the
  SKILL.md + its testable parser, justified as the loop + its seam).
- API refs in sketches use real modules: `phases.by_id`/`track_phases`,
  `models.load_models().resolve`, `plugin_gen.cc_alias` (added in step-1),
  `route_heuristic.classify`, `lifecycle.read_meta` — all verified
  present (design.md §1 FACTs).

## Build-time decisions

[!DECISION D-001] owner=impl-agent date=2026-07-10 refs=step-1,step-3
Step-1's `_is_interactive` originally special-cased a phase id
`"intake-triage"`. That id does not exist in `config/phases.yml` —
`intake-triage` is an agent invoked *from within* the `intake` phase
when routing confidence is low (see step-4/step-6), not a distinct
phases.yml phase. `phase_resolver.resolve_phase()` calls `ph.by_id
(phase_id)` first, so passing `"intake-triage"` would raise `KeyError`
before the interactive branch was ever reached — the check was dead
code. Fixed during step-3 (the RED test for the park behaviour
exposed it): `_is_interactive` now checks only
`meta.clarify_required and phase.id == "intake"`. The dead
`_INTERACTIVE_PHASES` set was removed.

[!DECISION D-002] owner=impl-agent date=2026-07-11 refs=step-6,step-8
step-6's "Interactive clarify (main-loop only)" section in
`intake-triage.md` already wrote the batch/serial branch referencing
`clarify_config.load_clarify_style()` — it was the natural place to
describe the full clarify flow in one edit rather than half-describing
it in step-6 and returning to patch it in step-8. step-8's tests for
this wiring (`test_batch_style_uses_ask_user_question`,
`test_serial_style_asks_one_question_at_a_time`) therefore pass
immediately (no RED phase for that specific assertion) — they still
serve as regression tests locking the content in, and step-8 adds the
genuinely new coverage: C-006 (clarify_config never imported by
runner.py/manual-CLI), the discovery-split behavior (AC-11), and the
docs parity (README, process.md, tracks.md) that step-6 did not touch.

[!DECISION D-003] owner=impl-agent date=2026-07-11 refs=step-7,review
Codex external review (`.klc/tickets/KLC-052/codex_external_review.md`,
verdict CHANGES REQUESTED) found two HIGH findings after build was
believed complete:
1. `/klc:run` had no `klc-plugin/commands/run.md` entry — the actual
   plugin slash-command surface — even though `klc-plugin/skills/run/
   SKILL.md` and the README documented it. `plugin_gen.py` now
   generates `commands/run.md` pointing at `SKILL.md` as the single
   source of truth; `test_plugin_manifest.py`'s `LIFECYCLE_CMDS` gained
   `"run"` so this can't silently regress.
2. `SKILL.md` step 4's "Interactive gate — STOP" wording made the
   mandatory clarify pass (AC-7/AC-8) read as optional — a valid
   reading let the loop park on a low-confidence ticket without ever
   asking the clarify questions. Rewritten into two explicit branches:
   clarify gate = run the pass now, then continue; any other
   interactive gate = stop for real.
A third, non-blocking finding (`runner.run_agent(ticket=...)` doesn't
consume `phase_resolver`'s resolved model, only its interactive flag)
was left as a follow-up per the review's own assessment — current call
sites always pass a consistent `track`, so it's a latent contract gap,
not a live bug.

[!DECISION D-004] owner=impl-agent date=2026-07-11 refs=step-1,review
An independent fresh-agent review (general-purpose, no prior
conversation context — the mandatory pre-review-report check since
this environment has no dedicated `code-reviewer` agent type) found a
HIGH bug missed by both internal review and the codex external review:
`phase_resolver.resolve_phase()`'s `agent_type` was derived from
`phase_id` directly (`klc-plugin/agents/{phase_id}.md`), but 5 of 14
real phases point at a differently-named shared agent file (`build`
-> `impl.md`, `acceptance-test-plan`/`detailed-test-plan` ->
`test-planner.md`, `manual` -> `manual-check.md`, `learn` ->
`retrospective.md`). This silently returned `agent_type=None` for
`build` — the single most-executed phase for every S/M/L ticket —
breaking AC-2's Task-tool dispatch for the majority of real phase
executions. No existing test caught it because every test up to this
point only resolved phase ids where `phase_id == prompt stem` (design,
discovery) or where the bug was masked by the always-inline path
(xs-build). Fixed by deriving the agent filename from
`phase.prompt`'s stem instead; added a parametrized regression test
covering every phase in `phases.yml` against its real expected agent.

IMPL_PLAN_DRAFT KLC-052
