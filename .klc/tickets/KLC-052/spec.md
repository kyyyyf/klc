---
ticket: KLC-052
kind: tech
authority: human
last_generated: 2026-06-26T00:00:00Z
risk_tags: [user-facing]
---

# KLC-052 — Main-agent lifecycle orchestrator + mandatory intake clarify gate

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

## Problem / Context

The klc-plugin is a thin adapter; its slash-command skills only drive
**state transitions** (each `SKILL.md` shells out to `klc <verb>`).
Nothing connects "ticket is in phase X" to "dispatch subagent klc-X,
then advance". Separately, a one-sentence ticket reaches discovery with
no enrichment, and a *background* discovery subagent has no interactive
channel — so it dumps an oversized spec instead of asking. (This very
discovery run is the proof: it could not call `AskUserQuestion` and
emitted a 7-AC / 3-option spec for what was nominally an XS ticket.)

- FACT: every plugin command skill is "Run `klc <verb> $ARGUMENTS` via
  Bash and show the result"; no orchestration loop exists. src=`klc-plugin/skills/next/SKILL.md`, `klc-plugin/skills/ack/SKILL.md` verified=2026-06-26
- FACT: per-phase subagents exist as `klc-plugin/agents/klc-<phase>.md`
  with resolved `model:` frontmatter, generated from `core/agents/*.md`. src=`klc-plugin/agents/discovery.md:1-4`, `core/skills/plugin_gen.py:90-112` verified=2026-06-26
- FACT: `klc ack --auto` applies gate-policy — it auto-advances only
  when `gate_policy.evaluate` reports clean signals AND there is an
  unambiguous forward pick; otherwise it does not advance. This IS the
  run-to-gate throttle (KLC-045). src=`core/phases/ack.py:54-55,170-179`, `core/skills/gate_policy.py:74` verified=2026-06-26
- FACT: the route heuristic already emits a `confidence`
  ("low"|"medium"|"high") and a `route_decision`
  ("triage"|"full-discovery"|"trust"); a short, no-signal ticket is
  "low". This ticket's own meta has `route_confidence: "low"`,
  `route_decision: "triage"`. src=`core/skills/route_heuristic.py:99-102,168-261`, `.klc/tickets/KLC-052/meta.json` verified=2026-06-26
- FACT: `core/agents/intake-triage.md` already classifies + enriches
  `raw.md`, but is **opt-in** ("Runs only when intake recommends it")
  and is not interactive. src=`core/agents/intake-triage.md:1-6` verified=2026-06-26
- FACT: phases are skipped per track via `tracks:` in `phases.yml`; XS
  routes through `discovery-lite` while M routes through full
  `discovery`. src=`config/phases.yml` (tracks fields), `config/models.yml` (per_track.XS.discovery-lite) verified=2026-06-26

RESOLVED (Q-001/Q-002/Q-003 from the prior pass): "statuses" = lifecycle
phases (one `klc-<phase>` subagent each); loop scope = run-to-gate;
build = plugin skill (Option A), no new CLI verb.

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

## Non-goals

- Replacing the headless `core/skills/runner.py` dispatch path — it
  coexists with the main-loop orchestrator (overlap noted as a risk).
- Changing the `phases.yml` state set or `gate_policy` evaluation logic
  (KLC-045 is reused as-is, not modified).
- Auto-answering or auto-acking human gates (excluded by AC-5/AC-10).
- A new throttle mechanism for run-to-gate (excluded by AC-4).

## Constraints

> [!CONSTRAINT C-001] source=klc-plugin/README.md
> The plugin stays a thin adapter: orchestration must not duplicate klc
> CLI logic. Dispatch decisions derive from existing sources of truth
> (`phases.yml`, the generated `agents/` set), not a hand-kept map.

> [!CONSTRAINT C-002] source=core/skills/plugin_gen.py:90-112
> Per-phase model pinning comes from `models.yml` via `plugin_gen.py`.
> The orchestrator dispatches through the generated `klc-<phase>`
> subagents so model frontmatter is honored; it never hardcodes models.

> [!CONSTRAINT C-003] source=core/phases/ack.py:170-179
> The run-to-gate throttle is `klc ack --auto` + KLC-045 gate-policy.
> No new throttle is introduced.

> [!CONSTRAINT C-004] source=docs/tracks.md
> Spec/artifact size MUST be proportional to track: XS → 1–2 ACs and no
> options block; S → ~3 ACs; M+ → full options analysis. (This spec is
> sized to M, which the expansion justifies. The prior S-sized pass
> over-produced — encode the rule so it does not recur.)

> [!CONSTRAINT C-005] source=core/skills/runner.py (no interactive channel)
> HARD RULE: the headless `runner.py` executor NEVER executes
> interactive phases (clarify, picks, decision gates) — it has no
> interactive channel to the user. The headless path PARKS at such
> phases; the human clears them in the client (`/klc:run`) or via the
> manual CLI. The Task-tool (in-session) executor is the only one that
> may run interactive phases.

> [!CONSTRAINT C-006] source=this spec (AC-12), YAGNI
> `clarify.style` has exactly two values: `batch` | `serial`. No `auto`,
> no `hybrid`, and no per-track override. The key is global. Additional
> styles or scoping are an explicit future extension, deliberately out
> of scope now.

## Affected modules

- klc-plugin/agents: new `skills/run/` orchestrator skill; subagents dispatched per phase; phase→agent consistency. (FACT src=klc-plugin/agents/, klc-plugin/skills/ verified=2026-06-26)
- core/agents: `intake-triage.md` becomes the mandatory clarify machinery; subagent contracts gain the structured completion signal. (FACT src=core/agents/intake-triage.md verified=2026-06-26)
- core/skills: `plugin_gen.py` (phase→agent resolution / source of truth); `route_heuristic.py` (confidence drives the mandatory gate); `runner.py` (overlap with the new main-loop path to reconcile). (FACT src=core/skills/plugin_gen.py, core/skills/route_heuristic.py, core/skills/runner.py verified=2026-06-26)
- core/phases: `intake.py` triggers the mandatory clarify on low confidence; `ack.py --auto` is the throttle (reused). (FACT src=core/phases/intake.py, core/phases/ack.py:54-179 verified=2026-06-26)
- config: `phases.yml` (track→phase routing, discovery split), `models.yml` (per-phase models), and a new `config/clarify.*` (clarify config home — exact filename pinned in design; holds the global `clarify.style`). (FACT src=config/phases.yml, config/models.yml verified=2026-06-26)
- docs: README + `docs/` execution-surface and tracks docs must reflect the orchestrator, the clarify gate, and the proportionality rule. (FACT src=klc-plugin/README.md, docs/process.md, docs/tracks.md verified=2026-06-26)

## Approaches (shortlist — detail in design/options.md)

- Option A: Orchestrator skill in the plugin — main agent drives Task dispatch (picked).
- Option B: Deterministic orchestrator verb in the klc CLI; plugin relays.
- Option C: Status quo + docs only (rejected — does not satisfy the ask).

Picked: Option A (Orchestrator skill in the plugin) — `/klc:run <KEY>` drives a
run-to-gate loop in the main-loop prompt: route-aware dispatch (XS inline,
M/L → `klc-<phase>` subagents), structured completion signals,
`ack --auto` throttle, retry-once-then-stop on failure. The mandatory
clarify gate lives in the main loop (Deliverable 2) precisely because
`AskUserQuestion` needs the interactive channel a background subagent
lacks. Phase→agent set derived from the generated `klc-plugin/agents/`
directory and `phases.yml` (no parallel map).

## Open questions

All discovery-blocking questions are resolved. No `blocks=discovery`
items remain.

- Q-001 (RESOLVED): "statuses" = lifecycle phases.
- Q-002 (RESOLVED): loop scope = run-to-gate.
- Q-003 (RESOLVED): build approach = Option A (plugin skill).
- Q-004 (RESOLVED — direction; detail deferred to design): One resolver,
  two executors, coexisting; executor chosen by ENTRY POINT not by phase.
  - One resolver: `phase → (prompt_path, model, agentType)` from a single
    source of truth (`phases.yml` + generated `klc-plugin/agents/` +
    `models.yml`). Both executors consume it (kills phase→agent drift;
    satisfies C-001/C-002).
  - Two executors coexist: Task-tool (in-session, interactive) and
    `core/skills/runner.py` (headless subprocess). Selection:
    `/klc:run` (attended) → Task; `klc init --auto`/CI (unattended) →
    runner.py.
  - HARD RULE: runner.py NEVER executes interactive phases (clarify,
    picks, decision gates). Headless parks at them; the human clears them
    in the client or manual CLI. (Captured as C-005.)
  - Still open for design: where the resolver module lives, and how
    budget-guard + token-telemetry (currently only in runner.py) are
    provided on the Task-tool path.

## Estimate
- complexity: 3
- uncertainty: 1
- risk: 2
- manual: 1
- total: 7
- track: M

(Blast-radius: unavailable — `modules.json` carries only name/path
pairs, no `depended_by` reverse edges. src=`.klc/index/modules.json`
verified=2026-06-26. Scored conservatively. Complexity=3: two coupled
deliverables spanning intake, discovery split, plugin orchestration, and
gate-policy reuse across `core/phases`, `core/skills`, `core/agents`,
`klc-plugin`, and `config`. Risk=2: the orchestrator auto-advances the
lifecycle (user-facing) and overlaps the existing `runner.py` path,
though human gates and gate-policy bound it. Total 7 maps to M, which
restores the first-pass M call now that scope has expanded; M-track
includes full discovery, resolving the earlier track/phase mismatch.)
