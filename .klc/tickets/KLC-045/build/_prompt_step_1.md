# Agent prompt — KLC-045 · build:work · step-1

Ticket: **KLC-045** · track: **M** · kind: **feature**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Classify every state-machine pick by how much human judgment it needs, and make that
classification machine-readable, so a future autonomous runner (KLC-046) can auto-advance
the safe transitions and pause on the ones that genuinely need a human. Concretely: add a
`gate` level to each pick in `phases.yml`, a pure predicate that decides whether a
`conditional` pick may auto-proceed given the current signals, and a hook that lets
`klc ack --auto` act on that predicate while leaving manual `klc ack` untouched.

## Acceptance Criteria

- [ ] AC-1: The `Pick` dataclass (`core/skills/phases.py`) gains a `gate` field
  (`auto|conditional|decision`, default `decision`), parsed from `phases.yml`; an unknown
  value raises at load time (fail-closed).
- [ ] AC-2: Every pick in `phases.yml` carries an explicit `gate`. The decision gates are
  the spec approval (discovery / discovery-lite approve), the design pick, manual passed,
  and integrate merged; the rest are `conditional` or `auto` per the design.
- [ ] AC-3: `core/skills/gate_policy.py::evaluate(gate, signals) -> GateDecision` returns
  `proceed` for `auto`; `pause` for `decision`; for `conditional` it returns `proceed` only
  when every signal in `signals` is clean and `pause` (with reasons) otherwise.
- [ ] AC-4: A signal-collector `gate_policy.collect_signals(ticket, phase_id)` assembles the
  real signals (phase_completion advisory, scope expansion, sentinels, budget overrun,
  review verdict, route_confidence) into the dict `evaluate` consumes, without duplicating
  the underlying skills.
- [ ] AC-5: `klc ack <KEY> --auto` applies the policy: it auto-acks a `conditional` pick when
  signals are clean, and refuses (non-zero, naming the blocking reasons) when they are not or
  when the pick is a `decision`. Plain `klc ack` (no `--auto`) behaves exactly as today.
- [ ] AC-6: A `decision` pick is never auto-acked even with clean signals; a risk flag
  (scope expansion, sentinel hit, budget overrun, or low route_confidence) forces a pause on
  a `conditional` pick.

### Current step — step-1

**gate field on Pick + phases.yml annotations**

- **Goal:** parse a `gate` level per pick and require it on every pick. (AC-1, AC-2)
- RED: add `tests/integration/test_gate_policy.py::test_pick_gate_field_parsed` and
  `::test_every_pick_has_gate`. Fail today (no field, no annotations).
- **Interfaces:** `Pick.gate: str` (default `"decision"`) in `core/skills/phases.py`;
  `_parse_pick` reads `gate`, raising on a value outside `{auto, conditional, decision}`;
  a `gate:` line on every pick in `config/phases.yml`.
- **Expected:** known values parse; unknown raises at load; all picks annotated.
- **VERIFY:** `python3 -m pytest tests/integration/test_gate_policy.py -k gate_field -q`
- **COMMIT:** `KLC-045 step-1: gate level on Pick + phases.yml annotations`
- **Affected:** `core/skills/phases.py`, `config/phases.yml`,
  `tests/integration/test_gate_policy.py` (new).
- Depends-on: none.
- **Code sketch:**

```python
_GATES = {"auto", "conditional", "decision"}
def _parse_pick(d, phase_id):
    gate = d.get("gate", "decision")
    if gate not in _GATES:
        raise ValueError(f"phase {phase_id!r} pick {d.get('id')}: bad gate {gate!r}")
    return Pick(id=..., label=..., goto=..., supersede=..., gate=gate)
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
re-run `klc step KLC-045 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-045/impl-plan.md`
- Full spec: `.klc/tickets/KLC-045/spec.md`
- Full test-plan: `.klc/tickets/KLC-045/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-045 step-1` and
run `klc step KLC-045 2` to get the next step's card,
or `klc ack KLC-045 --pick 1` if this was the last step.
