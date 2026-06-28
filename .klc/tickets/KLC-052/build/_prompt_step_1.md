# Agent prompt — KLC-052 · build:work · step-1

Ticket: **KLC-052** · track: **M** · kind: **tech**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Two coupled deliverables that, together, let the main Claude Code agent
drive a ticket through its lifecycle while front-loading clarification:

1. **Lifecycle orchestrator** — the main agent reads a ticket's phase,
   dispatches the matching per-phase subagent (or runs XS inline),
   parses a structured completion signal, and auto-advances
   (run-to-gate) until the nearest human gate.
2. **Mandatory intake clarify gate** — when intake produces a
   low-confidence route, a clarify pass *always* fires in the main loop
   (it needs interactive `AskUserQuestion`), enriches `raw.md`, and
   re-routes. This fixes the "big spec from 3 words" problem upstream,
   at intake, rather than letting discovery guess.

The two are coupled: discovery is modeled as
`clarify (main-loop, interactive)` / `author (background subagent,
synthesis)`, and the orchestrator's run-to-gate loop naturally STOPS at
the clarify gate because it is a human-interaction point.

## Acceptance Criteria

### Deliverable 1 — Lifecycle orchestrator

1. AC-1: A new `klc-plugin/skills/run/SKILL.md` (`/klc:run <KEY>`) drives
   the main agent to resolve the current phase via `klc status` and act
   on it; it does not fabricate phase outputs itself.
2. AC-2 (route-aware dispatch — hard requirement): When the resolved
   phase is on the XS fast-track, the orchestrator performs that phase's
   work **inline** in the main loop (no subagent — per-subagent overhead
   is not worth it for XS). For M/L phases it dispatches the matching
   `klc-<phase>` subagent via the Task tool. The XS-vs-subagent decision
   is derived from `meta.json:track` and the phase's `tracks:` in
   `phases.yml`.
3. AC-3 (structured completion signal — hard requirement): Phase
   subagents return a structured object, not free text:
   `{phase, signal, artifacts[], blocking_questions[], next_action}`.
   The orchestrator parses this object to decide the next step; it never
   re-reads phase artifacts to reconstruct state, keeping its own
   context small.
4. AC-4 (run-to-gate throttle): After a phase reports done, the
   orchestrator advances with `klc ack --auto` then `klc next`, looping
   into the next phase. It relies on the existing KLC-045 gate-policy in
   `ack --auto` as the throttle — it does NOT invent a new throttle.
5. AC-5 (stop conditions): The loop halts and surfaces to the human at
   the nearest human gate — defined as any of: (a) `ack --auto` declines
   to advance (gate dirty / ambiguous pick / `pick_required`), or (b)
   the structured signal's `blocking_questions[]` is non-empty.
6. AC-6 (failure handling — hard requirement): If a phase subagent dies,
   times out, or returns an unparseable/garbage signal, the orchestrator
   retries that phase **once**; if it fails again, it STOPS and surfaces
   the failure to the human (it does not advance, does not silently skip).

### Deliverable 2 — Mandatory intake clarify gate

7. AC-7 (mandatory gate): When `route_confidence == "low"` after
   `klc intake`, a clarify pass is **mandatory** (always fires) — it is
   not opt-in. The gate firing is unconditional on low confidence; it
   does not require the user to produce content (see AC-10).
8. AC-8 (main-loop, interactive): The clarify pass runs in the main loop
   and uses a single `AskUserQuestion` call carrying 2–4 high-leverage,
   design-changing questions (batched, not serial). Rationale: a
   background subagent has no interactive channel — that is exactly why
   discovery could not ask and over-produced.
9. AC-9 (reuse + write-back + re-route): The clarify pass reuses the
   existing `core/agents/intake-triage.md` machinery. Answers are
   written back into `raw.md`, then the ticket is re-routed
   (route recomputed) before discovery proceeds.
10. AC-10 (no-op escape): If the user has nothing to add, answering
    "nothing to add" satisfies the gate and the ticket proceeds.
    Mandatory means the gate always fires, not that the user must add
    content.
11. AC-12 (configurable clarify style): The clarify dialog style is
    configurable via `clarify.style: batch|serial`, default `batch`
    (AskUserQuestion, up to 4 batched questions). The key is GLOBAL
    across all tracks (no per-track override). It governs ONLY the
    in-client interactive main-loop path; the manual-CLI path (human
    edits raw.md) and the headless path (ticket parks) ignore it.
    `serial` = prose questions one at a time (superpowers-style).

### Coupling

11. AC-11 (discovery split): Discovery is modeled as
    `clarify (main-loop, interactive)` and `author (background subagent,
    synthesis with enriched input)`. The orchestrator's run-to-gate loop
    STOPS at the clarify gate because it is a human-interaction point
    (consistent with AC-5 and AC-8).

### Current step — step-1

**phase_resolver as single phase→agent source of truth**

- **Goal**: Add `core/skills/phase_resolver.py` — the single
  `resolve_phase(ticket, phase_id) -> ResolvedPhase` that both executors
  will consume, derived only from `phases.yml` + `models.yml` + the
  generated `klc-plugin/agents/` set + `meta.json:track`.
- **RED**: write `tests/integration/test_orchestrator_dispatch.py::test_dispatch_decision_derives_from_meta_and_phases_yml` — assert an XS-track ticket on an XS-eligible phase yields `runs_inline=True` and an M-track ticket yields `runs_inline=False` with `agent_type == "klc-<phase>"`, using only `meta.track` + `phases.track_phases`. Cites test-plan AC-2 row 3.
- **GREEN**: implement `ResolvedPhase` dataclass + `resolve_phase` composing `phases.by_id(phase_id).prompt`, `load_models().resolve(phase_id, track=track).model`, `plugin_gen.cc_alias(model)`, existence of `klc-plugin/agents/{phase_id}.md`, and `runs_inline = track == "XS" and phase in phases.track_phases("XS")`. Also expose `cc_alias` publicly in `plugin_gen.py` (rename usage; keep `_cc_alias` as a thin alias for back-compat).
- **VERIFY**: `python3 -m pytest tests/integration/test_orchestrator_dispatch.py::test_dispatch_decision_derives_from_meta_and_phases_yml -q`
- **Expected**: `1 passed`
- **COMMIT**: `KLC-052 step-1: add phase_resolver.resolve_phase as the single phase→agent source of truth`
-

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
re-run `klc step KLC-052 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-052/impl-plan.md`
- Full spec: `.klc/tickets/KLC-052/spec.md`
- Full test-plan: `.klc/tickets/KLC-052/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-052 step-1` and
run `klc step KLC-052 2` to get the next step's card,
or `klc ack KLC-052 --pick 1` if this was the last step.
