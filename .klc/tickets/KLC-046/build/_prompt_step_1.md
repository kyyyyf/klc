# Agent prompt — KLC-046 · build:work · step-1

Ticket: **KLC-046** · track: **L** · kind: **feature**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Close the autonomy capstone: a `klc run <KEY>` loop that drives a ticket through the state
machine on its own — dispatching the phase agent at each `:work`, running the completion
gates, and applying the KLC-045 gate-policy to either auto-advance a clean `conditional`
gate or pause and notify. Bounded by guardrails so it can never silently take an
irreversible or risky action: a budget ceiling, a cap on consecutive auto-transitions,
mandatory pause on outward-facing/irreversible transitions, and a pause on any risk gate.

## Acceptance Criteria

- [ ] AC-1: `klc run <KEY>` reads the current state; at a `:work` state it dispatches the
  phase agent (build via KLC-042's orchestrator, others via `runner.run_agent`) with the
  resolved model, then re-reads state.
- [ ] AC-2: At `:ack-needed` it calls `gate_policy.collect_signals` + `evaluate`; on a clean
  `conditional` gate it auto-acks (via the KLC-045 `--auto` path) and continues; otherwise it
  pauses and emits a notification naming the reason.
- [ ] AC-3: A `decision` gate always pauses with a notification, even with clean signals.
- [ ] AC-4: Guardrails — the loop pauses (never proceeds) on: an integrate/merge transition
  or any step that would push to a remote; a budget ceiling reached; or a configurable cap of
  consecutive auto-transitions exceeded. Each pause states which guardrail fired.
- [ ] AC-5: A dry-run / simulation test drives a clean S ticket through build → review →
  integrate-pause without human input, and asserts the loop stops at the design pick and at
  the merge guardrail.
- [ ] AC-6: The runner writes a per-ticket run log (transitions taken, gates evaluated,
  pauses with reasons) so a human resuming after a pause sees exactly what happened.

### Current step — step-1

**guardrail predicate**

- **Goal:** a pure function deciding whether the loop must pause before an auto-ack. (AC-4)
- RED: add `tests/integration/test_autorunner.py::test_run_guardrails` covering integrate,
  budget ceiling, and the consecutive-auto cap. Fails today (no module).
- **Interfaces:** `core/skills/autorunner.py::guardrail(ticket, phase_id, pick, n_auto,
  cap) -> str | None` returning a reason string when a guardrail fires, else `None`.
- **Expected:** integrate or a merge/push pick → reason; any budget counter at limit →
  reason; `n_auto >= cap` → reason; otherwise `None`.
- **VERIFY:** `python3 -m pytest tests/integration/test_autorunner.py -k guardrail -q`
- **COMMIT:** `KLC-046 step-1: autorunner guardrail predicate`
- **Affected:** `core/skills/autorunner.py` (new), `tests/integration/test_autorunner.py` (new),
  `config/budgets.yml`.
- Depends-on: none.
- **Code sketch:**

```python
_OUTWARD = {"integrate"}
def guardrail(ticket, phase_id, pick, n_auto, cap):
    if phase_id in _OUTWARD or "merge" in pick.label or "push" in pick.label:
        return "outward-facing/irreversible — human required"
    if _any_budget_at_limit(ticket):
        return "budget ceiling reached"
    if n_auto >= cap:
        return f"consecutive-auto cap {cap} reached"
    return None
```

**Affected files**:


**Expected tests**:



### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.

### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/home/ek/projects/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-046 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-046/impl-plan.md`
- Full spec: `.klc/tickets/KLC-046/spec.md`
- Full test-plan: `.klc/tickets/KLC-046/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-046 step-1` and
run `klc step KLC-046 2` to get the next step's card,
or `klc ack KLC-046 --pick 1` if this was the last step.
