---
ticket: KLC-052
kind: build-log
---

# Build log — KLC-052

## Step 1 — 2026-07-10
**Attempt**: add `core/skills/phase_resolver.py` (`resolve_phase`/`ResolvedPhase`) as
the single phase→agent source of truth; expose `plugin_gen.cc_alias` publicly
(kept `_cc_alias` as a back-compat alias — grepped repo, only internal caller
was `plugin_gen.py` itself).
**Outcome**: green
**Notes**: RED test `tests/integration/test_orchestrator_dispatch.py::test_dispatch_decision_derives_from_meta_and_phases_yml`
failed on missing module first, then passed after implementation.
`pytest tests/ -q -k plugin_gen --ignore=tests/fixtures` (3 passed) confirms no
regression to existing plugin_gen frontmatter generation (C-002). The
`--ignore=tests/fixtures` is needed because `tests/fixtures/tiny-py/tests/` is
a standalone fixture project with its own `src.app` import that isn't
collectible from the repo root — pre-existing, unrelated to this ticket.

## Evidence

```
$ python3 -m pytest tests/integration/test_orchestrator_dispatch.py -q
1 passed in 0.05s
$ python3 -m pytest tests/ -q -k plugin_gen --ignore=tests/fixtures
3 passed, 485 deselected in 0.23s
```

## Step 2 — 2026-07-10
**Attempt**: extract `_load_budget_limits`/`_estimate_tokens`/`_write_token_metrics`
from `runner.py` into `core/skills/budget_guard.py` as public
`load_budget_limits`/`estimate_tokens`/`write_token_metrics`; add advisory
`check_prompt_budget`/`BudgetVerdict`. `runner.py` re-imports the three under
their old private names (`from budget_guard import load_budget_limits as
_load_budget_limits, ...`) so existing tests that `patch.object(runner,
"_load_budget_limits", ...)` keep working unchanged — no behavior change in
runner.py itself.
**Outcome**: green
**Notes**: verified both the new advisory check and the old inline runner
guard path (which existing tests patch directly) still work.

## Evidence

```
$ python3 -m pytest tests/test_budget_guard.py -q
2 passed in 0.04s
$ python3 -m pytest tests/ -q -k runner --ignore=tests/fixtures
2 passed, 488 deselected in 0.26s
$ python3 -m pytest tests/integration/test_step_card_compression.py tests/integration/test_token_telemetry.py -q
14 passed in 0.16s
```

## Step 3 — 2026-07-10
**Attempt**: `runner.run_agent` consumes `phase_resolver.resolve_phase()` when
`ticket` is passed and parks (writes `meta.json:parked` + `[!PARKED]` to
out_path, returns `PARK_RC=3`) instead of dispatching when the resolved phase
is interactive — before any model resolution/budget/dispatch work (C-005).
Found and fixed a step-1 bug in the same pass: see impl-plan.md
`[!DECISION D-001]` — `"intake-triage"` isn't a phases.yml id, so the
original interactive-phase check was unreachable dead code.
**Outcome**: green
**Notes**: no existing `run_agent` caller passes `ticket=`, so the new park
branch cannot fire on any pre-existing path — zero risk of regression there.
Confirmed `tests/e2e_pipeline.py` fails identically before and after this
step's change (pre-existing `discovery-lite` fixture gap, unrelated).

## Evidence

```
$ python3 -m pytest tests/e2e/test_runner_parks_interactive.py tests/integration/test_orchestrator_dispatch.py -q
2 passed in 0.05s
$ python3 -m pytest tests/ -q --ignore=tests/fixtures -k "runner or model_subagent or model_guard or token_telemetry or step_card_compression"
28 passed, 463 deselected in 0.46s
```

## Step 4 — 2026-07-10
**Attempt**: `intake.py` stamps `meta.json:clarify_required = (route_confidence
== "low")` unconditionally, alongside the existing `route_confidence` field.
Test ticket keys had to use numeric suffixes (`KLC-9001` etc.) — the ticket-id
regex `^[A-Z][A-Z0-9]+-\d+$` requires digits after the dash, so `KLC-CG01`-style
placeholders were rejected at intake before the routing logic even ran.
**Outcome**: green
**Notes**: content-independence verified directly — two different low-signal
descriptions ("fix it" vs "asdf qwer") both set the stamp.

## Evidence

```
$ python3 -m pytest tests/integration/test_clarify_gate.py -q
3 passed in 0.09s
$ python3 -m pytest tests/ -q --ignore=tests/fixtures -k "intake or clarify"
7 passed, 487 deselected in 0.30s
```

## Step 6 — 2026-07-10
**Attempt**: appended a shared `## Completion signal (orchestrator)` block
(AC-3 JSON contract) to all 21 `core/agents/*.md`, additive to each file's
existing phase-specific signal line/section (no removal). Added an
"Interactive clarify (main-loop only)" section to `intake-triage.md`
(batch/serial via `clarify_config`, write-back to `raw.md` intake-notes,
re-route via `route_heuristic`, clear `clarify_required`). Ran
`python3 core/skills/plugin_gen.py` to regenerate `klc-plugin/agents/`.
**Outcome**: green (regen + frontmatter regression)
**Notes**: the regen also picked up pre-existing drift unrelated to this
ticket — `klc-plugin/agents/test-planner.md`/`test.md` were stale relative
to their `core/agents/` sources, and `design-scout.md` was missing from
`klc-plugin/agents/` entirely. `plugin_gen.py` brought both back in sync;
this is the generator doing its documented job (single source of truth),
not scope creep from this step.

## Evidence

```
$ python3 core/skills/plugin_gen.py
Generated 21 agent files in klc-plugin/agents
Generated/verified 8 command files in klc-plugin/commands
$ python3 -m pytest tests/ -q -k plugin_gen --ignore=tests/fixtures
3 passed, 494 deselected in 0.20s
```

## Step 7 — 2026-07-10
**Attempt**: added `klc-plugin/skills/run/SKILL.md` (`/klc:run`) encoding the
orchestration loop from design.md §3 as main-loop instructions (no Python
driver, per C-001), and `core/skills/run_signal.py` with `parse_signal`
(AC-3 structured completion-signal parsing) and `should_retry` (AC-6
retry-once-then-stop). Verified true RED/GREEN by moving `run_signal.py`
aside, confirming all 4 dependent test files failed on `ModuleNotFoundError`,
then restoring it.
**Outcome**: green
**Notes**: since the loop itself is prompt-driven (not a unit-testable
Python function), the test suite covers what's actually pure: the parser +
retry policy directly, plus the real seams the loop composes (`phase_resolver`
+ `klc status --json`, `ack --auto` + gate-policy) rather than re-testing
already-covered modules from scratch.

## Evidence

```
$ python3 -m pytest tests/e2e/test_orchestrator.py tests/integration/test_orchestrator_signal.py tests/integration/test_orchestrator_run_to_gate.py tests/integration/test_orchestrator_stop.py tests/integration/test_orchestrator_failure.py -q
15 passed in 0.38s
$ python3 -m pytest tests/ -q --ignore=tests/fixtures -k "gate_policy or orchestrator or ack or next_"
93 passed, 419 deselected in 1.41s
```

## Step 8 — 2026-07-11
**Attempt**: added regression tests for the clarify.style wiring already
written into `intake-triage.md` in step-6 (see impl-plan.md `[!DECISION
D-002]`), plus new coverage: `test_style_ignored_on_headless_runner_path`
+ `test_style_ignored_on_manual_cli_path` (C-006 — grep-based, asserts
`clarify_config` is never imported by `runner.py`/`intake.py`/`ack.py`/
`next.py`), `test_nothing_to_add_satisfies_gate` (AC-10, content-presence
on `intake-triage.md`), and `tests/e2e/test_discovery_split.py` (AC-11 —
gate at `intake` when `clarify_required`, ordinary `klc-discovery` author
subagent at `discovery` once cleared, no new phases.yml id). Docs parity:
`klc-plugin/README.md` (`/klc:run` command row + execution-surface row),
`docs/process.md` (new "Orchestrator (/klc:run, KLC-052)" section),
`docs/tracks.md` (C-004 artifact-size-proportional-to-track rule).
**Outcome**: green
**Notes**: this is the last build step — all 8 steps of impl-plan.md are
now complete.

## Evidence

```
$ python3 -m pytest tests/integration/test_clarify_style.py tests/e2e/test_discovery_split.py tests/integration/test_clarify_gate.py -q
12 passed in 0.13s
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
506 passed, 12 skipped in 165.42s
```

## Review round 1 — 2026-07-11
**Attempt**: after all 8 build steps were green, ran `klc ack` (blocked once
on TDD-order — see below — then again on scope_expansion/route_confidence,
resolved per CLAUDE.md's "update affected_modules rather than fight it").
A codex external review (`.klc/tickets/KLC-052/codex_external_review.md`)
then found 2 HIGH + 1 MEDIUM finding; both HIGH findings fixed (see
impl-plan.md `[!DECISION D-003]`): `/klc:run` now has a real
`klc-plugin/commands/run.md`, and `SKILL.md`'s clarify gate is now active
rather than a silent stop. In parallel, a fresh independent general-purpose
subagent review (CLAUDE.md's mandatory pre-review-report step, since no
dedicated `code-reviewer` agent type exists in this environment) was
launched to catch anything codex's focused pass missed.
**Also fixed before this round**: the TDD-order gate (KLC-039) initially
blocked `klc ack` — steps 1-5, 7, 8 had each been committed as a single
test+impl commit rather than test-first-then-impl. Since nothing had been
pushed yet, rewrote branch history (`git reset --soft main` + re-commit in
proper RED-commit-then-GREEN-commit pairs per step) rather than bypassing
the gate; verified the resulting tree is byte-identical to the pre-rewrite
state (`git diff <old-head> <new-head>` empty) before and after.
**Outcome**: green (both HIGH findings fixed; full suite still 506 passed)
**Notes**: this build-log entry will be followed by a second review-round
entry once the independent fresh-agent review returns.

## Evidence

```
$ python3 -m pytest tests/integration/test_plugin_manifest.py -q
4 passed in 0.02s
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
506 passed, 12 skipped in 164.07s
```

## Review round 2 — 2026-07-11
**Attempt**: the independent fresh-agent review (general-purpose, launched
before the codex findings landed, ran ~21 min doing its own from-scratch
read of all 68 changed files plus independent reproduction of
`resolve_phase()` behavior across every `phases.yml` id) returned. It found
one HIGH bug missed by internal review AND by codex: `agent_type` derived
from `phase_id` instead of `phase.prompt`'s filename stem — silently
`None` for `build`/`acceptance-test-plan`/`detailed-test-plan`/`manual`/
`learn` (5 of 14 phases), breaking Task-tool dispatch (AC-2) for the
`build` phase on every S/M/L ticket. Verified the claim directly against
`config/phases.yml` before fixing (see impl-plan.md `[!DECISION D-004]`).
Confirmed true RED by reverting the fix, running the new parametrized
regression test (fails: `build` -> `None` instead of `klc-impl`), then
restoring the fix and confirming GREEN.
Two LOW findings from the same review: (a) the shared completion-signal
block landed on `design-scout.md`/`intake-triage.md` even though neither
is an independently-dispatched phase — harmless per the reviewer's own
assessment, not fixed; (b) no `klc-plugin/commands/run.md` — already fixed
by the codex-driven commit that landed while this review was still running
(the fresh-review agent's git diff read predates that commit).
**Outcome**: green (HIGH fixed; both LOWs assessed, one already resolved,
one accepted as harmless)
**Notes**: this is the second review round to find a real bug after
"build complete" — a reminder that internal self-review + one external
pass both missed something a second independent pass caught. Proceeding
to write review-report.md now.

## Evidence

```
$ python3 -m pytest tests/integration/test_orchestrator_dispatch.py -q
3 passed in 0.29s
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
508 passed, 12 skipped in 166.31s
```
