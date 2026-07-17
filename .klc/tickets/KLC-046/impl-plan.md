---
ticket: KLC-046
kind: impl-plan
design_choice: option-A-minimal
last_generated: 2026-06-24
---

# KLC-046 — Implementation plan (executable, for Sonnet)

Build target: a `klc run <KEY>` autonomous driver reusing the orchestrator, runner,
lifecycle, and KLC-045 gate-policy, bounded by guardrails. Per-step contract: **Goal / RED /
Interfaces / Expected / VERIFY / COMMIT / Affected / Code sketch / Depends-on**. Run after
each step: `python3 -m pytest tests/ -q --ignore=tests/fixtures`. COMMIT subjects verbatim.

## step-1 — guardrail predicate

- **Goal:** a pure function deciding whether the loop must pause before an auto-ack, with the
  outward-facing set and the budget helper both defined and tested against real data. (AC-4)
- RED: add `tests/integration/test_autorunner.py` with `test_guardrail_integrate_pauses`
  (phase-id `integrate` → reason — driven by phase-id, NOT a goto/label heuristic),
  `test_guardrail_budget_ceiling` (a fixture with `meta.budgets` counter at its limit →
  reason), `test_guardrail_cap` (`n_auto >= cap` → reason), and `test_guardrail_clean`
  (none → None). Fails today (no module). NOTE (audit fix #4): the earlier
  `test_guardrail_merge_pick_pauses` (pick goto/label heuristic) is REMOVED — outward
  classification is purely phase-id based; no phases.yml pick label contains "push", so the
  substring heuristic was inert.
- **Interfaces:** `core/skills/autorunner.py::guardrail(ticket, phase_id, n_auto, cap)
  -> str | None`. Outward-facing is driven by an explicit `_OUTWARD_PHASES = {"integrate"}`
  set (NOT a fragile label substring); the merge/push concern is covered because `integrate`
  is the only phase that merges/pushes in the state machine. If a future outward-facing
  transition is added, it must be added to `_OUTWARD_PHASES` (a comment says so). Budget
  reuse: `_any_budget_at_limit(ticket)` reuses `budget._load_limits()` and compares against
  `meta.budgets` with `current >= limit` (the same logic as `budget.cmd_check`). The
  consecutive-auto `cap` is a SEPARATE concern (audit fix #3): it is NOT a budget counter and
  must NOT be added to `.klc/config/budgets.yml` (that file feeds `budget._load_limits()` and
  hence `gate_policy`'s `budget_overrun` signal). `_cap()` has its own loader (see step-3).
- **Expected:** phase in `_OUTWARD_PHASES` → reason; any `meta.budgets` counter at/over its
  limit → reason; `n_auto >= cap` → reason; otherwise `None`.
- **VERIFY:** `python3 -m pytest tests/integration/test_autorunner.py -k guardrail -q`
- **COMMIT:** `KLC-046 step-1: autorunner guardrail predicate (explicit outward set + budget reuse)`
- **Affected:** `core/skills/autorunner.py` (new), `tests/integration/test_autorunner.py` (new),
  `config/budgets.yml`.
- Depends-on: none.
- **Code sketch:**

```python
import budget, lifecycle
_OUTWARD_PHASES = {"integrate"}  # add any future merge/push/outward phase here
def _any_budget_at_limit(ticket):
    limits = budget._load_limits(); cur = (lifecycle.read_meta(ticket).get("budgets") or {})
    return any(int(cur.get(c, 0)) >= lim for c, lim in limits.items())
def guardrail(ticket, phase_id, n_auto, cap):
    if phase_id in _OUTWARD_PHASES:
        return "outward-facing/irreversible (integrate/merge) — human required"
    if _any_budget_at_limit(ticket):
        return "budget ceiling reached"
    if n_auto >= cap:
        return f"consecutive-auto cap {cap} reached"
    return None
```

## step-2 — dispatch step

- **Goal:** dispatch the current `:work` phase agent with the resolved model. (AC-1)
- RED: add `test_run_dispatches_work_state` with an injected fake dispatch asserting build
  routes to the orchestrator and other phases to `run_agent`.
- **Interfaces:** `autorunner._dispatch(ticket, phase_id, dispatch)` — build →
  `build_orchestrator.run_build(ticket, dispatch=dispatch)`; else `runner.run_agent`.
  - **P1-A (codex): dispatch the RENDERED per-ticket card, not the generic role prompt.**
    `_card_path(ticket, phase_id)` renders `.klc/tickets/<KEY>/<phase>/_prompt.md` via
    `artefacts.write_prompt_card` (the SAME card the manual `klc ack`/`klc next` path writes
    on entering a `:work` phase — it carries the concrete key, resolved input paths, and
    output/ack instructions). Pass THAT path, never `core/agents/<phase>.md` (which is full
    of `<KEY>` placeholders). `_out_path` is the RESPONSE SINK
    (`.klc/tickets/<KEY>/<phase>/_response.md`) where `run_agent` writes the raw response —
    the DECLARED artifacts are written by the agent itself per the card.
  - Pass `track=` so it resolves the model internally (do NOT compute a `model` var and drop
    it) AND `ticket=` so `run_agent`'s interactive-park guard (C-005) fires: an interactive
    phase (e.g. a clarify-required intake) parks with `PARK_RC` → the loop pauses.
  - An empty-prompt checklist phase (observe/integrate) is not auto-dispatchable → return a
    non-zero sentinel so the loop pauses fail-closed. Returns the dispatch rc.
- **P1-B artifact-sufficiency is delegated to the track-aware gate (do NOT duplicate it).**
  An earlier `_missing_outputs` pre-check compared against `phase.outputs` from phases.yml —
  but that is a SUPERSET, not the required set: `can_complete_discovery_lite` is track-aware
  (XS needs only `spec.md`; S needs `spec.md`+`options-lite.md`+`impl-plan.md`; NEITHER needs
  `test-plan.md` though phases.yml lists it). Duplicating per-track rules drifted and wrongly
  blocked valid XS runs, so the pre-check was REMOVED. Authority is `ack --auto`'s
  `can_complete`: an insufficient dispatch returns rc 1 and the loop pauses fail-closed with
  the gate's own causal reason (surfaced per the fail-closed-loop note below). `_out_path` is
  the response sink where `run_agent` writes the raw response; the declared artifacts are the
  agent's to produce per the card.
- **Expected:** build routes to the orchestrator; other phases route to `run_agent` with the
  ticket's track; the rc is returned and a non-zero rc is surfaced to the loop.
- **VERIFY:** `python3 -m pytest tests/integration/test_autorunner.py -k dispatch -q`
- **COMMIT:** `KLC-046 step-2: autorunner phase dispatch`
- **Affected:** `core/skills/autorunner.py`, `tests/integration/test_autorunner.py`.
- Depends-on: step-1.
- **Code sketch:**

```python
def _dispatch(ticket, phase_id, dispatch):
    if phase_id == "build":
        return build_orchestrator.run_build(ticket, dispatch=dispatch)
    track = lifecycle.read_meta(ticket)["track"]
    return dispatch(phase_id, _prompt_path(ticket, phase_id),
                    _out_path(ticket, phase_id), track=track)
```

## step-3 — the run loop

- **Goal:** tie dispatch + gates + gate-policy + guardrails into one bounded loop that
  advances by invoking the SAME `klc ack --auto` path KLC-045 built (no re-implemented ack).
  (AC-1, AC-2, AC-3, AC-5, AC-7)
- **Audit fix #1 — the `:work` step:** `:work → :ack-needed` happens INSIDE `klc ack` (via
  `phase_completion.can_complete`), NOT in `lifecycle`. So at `:work` the loop dispatches
  then calls `ack --auto` — a single `--auto` from `:work` auto-detects completion and walks
  `:work → :ack-needed → (gate)` in one call. The loop must NOT just `continue` to re-read
  `:work` (that would spin forever).
- **rc disambiguation (AC-7, feature-off):** `ack --auto` returns rc 0 (advanced) or rc 2
  (gate pause — decision gate or dirty conditional). Any other non-zero rc is an error pause
  with its own message. Feature-off never returns the feature-on rc-1 sync errors.
- RED (the simulation MUST assert real state transitions, not a trace string):
  - `test_run_auto_acks_clean_conditional`: a fixture at a conditional `:ack-needed` with
    clean signals → loop calls the real `ack --auto`, `lifecycle.current_state` advanced.
  - `test_run_pauses_on_decision_gate`: at a `decision` gate → `paused_at` set, phase UNCHANGED.
  - `test_run_ml_design_decision_simulation` (AC-5a): an M/L fixture at `design:work` (or
    earlier) with a fake dispatch writing green artifacts → the loop HALTS at
    `design:ack-needed` (decision gate) with a reason. (S has no design phase — see below.)
  - `test_run_clean_s_ticket_simulation` (AC-5b): a real S fixture at `build:work` with a fake
    dispatch that writes green artifacts → `meta.json:phase` ACTUALLY walks build→review and
    HALTS at the integrate guardrail (`paused_at == "integrate"`), driving genuine
    `lifecycle`/`ack --auto` with only agent dispatch faked. A loop that only appends to a
    trace must FAIL this test.
  - `test_run_refuses_feature_on` (AC-7): with `state_feature.enabled()` monkeypatched True →
    the loop refuses, takes no transition, and returns a refusal reason.
- **Interfaces:** `autorunner.run(ticket, *, dispatch=None, cap=None) -> RunResult`
  (`transitions`, `paused_at`, `reason`). `_forced_pick(phase)` returns the `goto=="next"`
  pick (same resolver semantics as KLC-045's `_resolve_auto_pick`) — used only to CLASSIFY
  the pause reason (decision vs dirty-conditional), never to re-implement ack. `_ack_auto(
  ticket)` MUST invoke `core/phases/ack.py::run([ticket, "--auto"])` so the runner and a human
  `klc ack --auto` take the IDENTICAL transition. `_cap()` loads the consecutive-auto cap from
  its OWN loader (framework `config/budgets.yml` top-level `consecutive_auto_transitions`,
  with a module-constant default and a `KLC_AUTORUN_CAP` env override) — SEPARATE from
  `budget._load_limits()` (audit fix #3). Feature-off guard at entry: refuse if
  `state_feature.enabled()`.
- **Expected:** clean S ticket advances build→review without input and halts at the integrate
  guardrail; a clean M/L ticket halts at the design decision gate; a decision gate pauses with
  phase unchanged; feature-ON refuses.
- **VERIFY:** `python3 -m pytest tests/integration/test_autorunner.py -k "auto or decision or simulation or refuse" -q`
- **COMMIT:** `KLC-046 step-3: autorunner bounded run loop (reuses ack --auto path)`
- **Affected:** `core/skills/autorunner.py`, `tests/integration/test_autorunner.py`.
- Depends-on: step-2.
- **Code sketch:**

```python
import ack as ack_cmd            # core/phases/ack.py — reuse, do not reimplement
import state_feature
def _ack_auto(ticket):
    return ack_cmd.run([ticket, "--auto"])   # identical path a human would take
def run(ticket, *, dispatch=None, cap=None):
    if state_feature.enabled():
        return RunResult([], None, "refused: multi-user state feature ON — "
                                   "autonomous run is single-user (feature-off) only")
    cap = cap if cap is not None else _cap(); n_auto = 0; trace = []
    while True:
        pid, state = phases.parse_state(lifecycle.current_state(ticket))
        if state == "archived": break
        stop = guardrail(ticket, pid, n_auto, cap)   # BEFORE any outward/auto step
        if stop: return _pause(ticket, trace, pid, stop)
        if state in ("work", "ack-needed"):
            if state == "work":
                rc = _dispatch(ticket, pid, dispatch)
                if rc != 0:
                    return _pause(ticket, trace, pid, f"dispatch failed (rc={rc})")
            rc = _ack_auto(ticket)                     # walks work→ack-needed→gate
            if rc == 0:
                n_auto += 1; trace.append(pid); continue
            if rc == 2:
                return _pause(ticket, trace, pid, _gate_reason(ticket, pid))
            return _pause(ticket, trace, pid, f"ack --auto error (rc={rc})")
        else:  # a lingering :ack (rare in auto path)
            lifecycle.advance_to_next(ticket)
    return RunResult(trace, None, None)
```

## step-4 — notifications + run log

- **Goal:** record transitions and emit a notification on each pause. (AC-6)
- RED: add `test_run_writes_run_log` asserting the log captures transitions and the pause
  reason.
- **Interfaces:** `autorunner._notify(ticket, reason)` (stderr + optional PushNotification);
  `autorunner._log(ticket, entry)` appending to `.klc/tickets/<KEY>/run-log.md`.
- **Expected:** every transition and pause is logged with a timestamp passed in by the caller;
  the pause emits a notification.
- **VERIFY:** `python3 -m pytest tests/integration/test_autorunner.py -k run_log -q`
- **COMMIT:** `KLC-046 step-4: autorunner notifications + run log`
- **Affected:** `core/skills/autorunner.py`, `tests/integration/test_autorunner.py`.
- Depends-on: step-3.
- **Code sketch:**

```python
def _log(ticket, entry):
    p = klc_ticket_dir(ticket) / "run-log.md"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(entry + "\n")
```

## step-5 — klc run verb

- **Goal:** expose the loop as `klc run <KEY>`. (AC-1, AC-5)
- RED: add `test_run_registered` asserting the verb routes and accepts `--cap`.
- **Interfaces:** `core/phases/run.py::run(argv)` (argparse: `ticket`, `--cap`, `--json`);
  register `run` in `scripts/klc` dispatcher.
- **Expected:** `klc run <KEY>` drives the loop and prints the RunResult (or `--json`).
- **VERIFY:** `python3 -m pytest tests/integration/test_autorunner.py -k registered -q`
- **COMMIT:** `KLC-046 step-5: klc run verb`
- **Affected:** `core/phases/run.py` (new), `scripts/klc`, `tests/integration/test_autorunner.py`.
- Depends-on: step-4.
- **Code sketch:**

```python
def run(argv):
    ap = argparse.ArgumentParser(prog="klc run")
    ap.add_argument("ticket"); ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = autorunner.run(a.ticket, cap=a.cap)
    print(_render(res)); return 0 if res.paused_at is None else 2
```

## step-6 — docs parity

- **Goal:** document `klc run`, the guardrails, and the run log. (AC-4, AC-6)
- RED: not applicable — docs-only step. Rule cited: AC-1 through AC-6 + roadmap 6.2.
- **Interfaces:** prose only — `docs/process.md` gains an "autonomous runner" section
  describing `klc run`, the guardrail set, and that integrate/merge always pauses.
- **Expected:** `grep -rn "klc run" docs/process.md` returns the new content.
- **VERIFY:** `grep -rn "klc run" docs/process.md`
- **COMMIT:** `KLC-046 step-6: docs parity for the autonomous runner`
- **Affected:** `docs/process.md`.
- Depends-on: step-5.
- **Code sketch:** not applicable — documentation prose only (RED not applicable).

## Notes for the implementer

- One logical commit per step; COMMIT subjects verbatim. Depends on KLC-045 (gate_policy)
  and reuses KLC-042 (build_orchestrator, runner). Build after 045.
- Guardrails fail-closed: when a signal or classification is uncertain, pause.
- Never merge or push from the runner; integrate always pauses for a human.
- SINGLE-USER / feature-off only (AC-7). `state_tx` is a no-op here (state_feature.enabled()
  is False), so `ack --auto` behaves exactly as this plan assumes: rc 0 = advanced, rc 2 =
  gate pause. The loop refuses if `state_feature.enabled()` returns True.
- The consecutive-auto cap is NOT a budget counter — keep it out of `.klc/config/budgets.yml`
  / `budget._load_limits()` (audit fix #3); it has its own `_cap()` loader.
- **P2 (codex): validate the ticket exists BEFORE any `_log`/state mutation.** `run()` checks
  `klc_ticket_meta_file(ticket).exists()` first (like status.py/step.py); an unknown key gets
  a friendly refusal (rc 1) and NEVER creates a bogus `.klc/tickets/<BADKEY>/` dir.
- **Fail-closed loop (fresh review):** the whole loop body is wrapped so a corrupt
  `meta.json` / unreadable config becomes a LOGGED pause (rc 2), never a traceback — honouring
  the "pause when uncertain" contract. `ack --auto`'s stderr is captured and the FULL causal
  diagnostic is surfaced into the pause reason + run log — NOT just the last stderr line, which
  is usually the generic abort/remediation hint (e.g. for an incomplete phase the causal
  "Missing <artifact>" is the middle line; for scope expansion it is the first line). The
  feature-on refusal is also logged.
