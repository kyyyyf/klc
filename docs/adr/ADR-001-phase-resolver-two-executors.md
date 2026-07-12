---
number: 001
title: One phase→agent resolver, two executors, advisory budget on the Task path
status: Accepted
date: 2026-06-26
status_history:
  - {date: 2026-06-26, status: Proposed}
  - {date: 2026-07-12, status: Accepted, note: post-implementation review}
chosen_label: A
affected_modules: [core/skills, core/phases, core/agents, klc-plugin/agents, config]
references:
  - .klc/tickets/KLC-052/spec.md
  - .klc/tickets/KLC-052/design.md
  - .klc/tickets/KLC-052/design/options.md
lessons_learned:
  - The resolver seam was the right design, but its first implementation
    itself had a phase-id-vs-agent-name bug that defeated the seam's own
    purpose for 5/14 phases — see "Consequences" [revised] note below.
  - The prompt-reliability risk in the "Negative" consequences was not
    hypothetical — it materialized as a real HIGH review finding and had
    to be fixed before merge.
---

# ADR-001 — One phase→agent resolver, two executors, advisory budget on the Task path

> On acceptance, promote this file to `docs/adr/ADR-001-phase-resolver-two-executors.md`
> and add the `## ADRs` links to the affected module CLAUDE.md files
> (per `core/agents/adr.md` accept phase). `docs/adr/` does not yet exist.

## Status

Accepted (2026-07-12, post-implementation review). Proposed 2026-06-26.

## Context

KLC-052 makes the main Claude Code agent drive a ticket through its
lifecycle (`/klc:run`) while a headless `core/skills/runner.py` path
continues to exist for unattended runs. Both paths must answer the same
question — "for phase X, what prompt, what model, which subagent?" —
without drifting (C-001 single source of truth; C-002 model pinning from
`models.yml` via `plugin_gen.py`). Two further forces:

- C-005: `runner.py` must NEVER execute interactive phases (clarify,
  picks, decision gates) — it has no interactive channel.
- Budget-guard and token-telemetry currently live only inside
  `runner.py` (`_load_budget_limits`, `_estimate_tokens`,
  `_write_token_metrics`); the attended Task path has neither.

See `.klc/tickets/KLC-052/spec.md` (Q-004) and `design.md` §1–§2.

## Options

- **A — Orchestrator skill in the plugin (chosen).** `/klc:run` SKILL.md
  drives the main agent; a new pure `core/skills/phase_resolver.py` is the
  single source of truth both executors consume; budget logic is
  extracted to `core/skills/budget_guard.py` (hard on headless, advisory
  on Task); telemetry is best-effort on the Task path via an optional
  signal field. Cheapest; native CC model pinning honored.
- **B — Deterministic orchestrator verb in the klc CLI.** Rejected:
  larger `core/` surface (new verb + output contract), and the main agent
  still has to call Task, so it does not remove the prompt-reliability
  concern — it only adds a CLI contract a third path must respect.
- **C — Status quo + docs only.** Rejected: does not satisfy the ask
  (an orchestrator, not documentation).

## Decision

Adopt Option A with the two Q-004 resolutions:

1. **One resolver, two executors.** `core/skills/phase_resolver.py`
   exposes `resolve_phase(ticket, phase_id) -> ResolvedPhase`
   (`prompt_path` from `phases.yml`, `model`/`cc_model` from `models.yml`
   via `plugin_gen.cc_alias`, `agent_type` from the generated
   `klc-plugin/agents/` set, `runs_inline` from `meta.track` ×
   `phases.yml:tracks`, `interactive` from the clarify stamp + ack picks).
   `runner.py` and `/klc:run` both consume it; no parallel map exists.
2. **Budget advisory + best-effort telemetry on the Task path.** Extract
   the three runner helpers into `core/skills/budget_guard.py`. The
   headless path keeps HARD pre-spend enforcement; the Task path runs an
   ADVISORY `check_prompt_budget` pre-dispatch (hard breach → blocking
   question + STOP, soft breach → warn + proceed) and records telemetry
   only when the subagent self-reports it (`source="reported"`).
   Hard enforcement is intentionally NOT attempted on the Task path
   because the orchestrator cannot measure or interrupt the subagent's
   real context — a faked limit would be a false gate.

## Consequences

### Positive

- A single tested seam (`phase_resolver`) eliminates phase→agent drift
  across the attended and headless paths (kills Option A's main con).
  **[revised]** The seam design was correct, but its first
  implementation keyed `agent_type` off `phase_id` instead of
  `phase.prompt`'s filename stem — silently `None` for 5 of 14 phases
  (`build`, `acceptance-test-plan`, `detailed-test-plan`, `manual`,
  `learn`), breaking Task-tool dispatch for `build` on every S/M/L
  ticket. Every test written up to that point happened to resolve only
  phases where `phase_id == prompt stem`, so the bug shipped past
  internal review and one external (codex) review pass before an
  independent fresh-agent review caught it. The seam concept still
  holds — one function, one source of truth — but "single seam" is not
  "correct by construction"; it still needs coverage across every real
  input, not just the ones a hand-picked test happens to exercise.
- Model pinning is honored natively by Claude Code subagent frontmatter;
  the orchestrator never hardcodes a model (C-002).
- The same `config/budgets.yml` governs both paths; no duplicated limits.
- C-005 is enforced in one place (`runner.py` parks on `interactive`).

### Negative

- Orchestration lives partly in a prompt (`run/SKILL.md`); reliability
  depends on the main agent following the loop. Mitigated by pushing all
  *decisions* into the tested resolver + `phases.yml`, leaving the prompt
  to only sequence calls. **[revised]** This risk materialized, not just
  in theory: the first draft of step 4 said "Interactive gate — STOP"
  for both the mandatory clarify gate and ordinary human-pick gates,
  mentioning the clarify `AskUserQuestion` pass only as an example. A
  codex external review flagged that a plausible reading let the loop
  park on a low-confidence ticket without ever asking the clarify
  questions — defeating AC-7/AC-8's "always fires" requirement. Fixed
  by splitting the step into two explicit branches before merge, but
  the fact that ambiguous prose in a *decision-free* sequencing prompt
  could still produce a wrong decision confirms this negative
  consequence was real, not just a theoretical risk to note and move on.
- Token telemetry on the Task path is incomplete when a subagent does not
  self-report (observability gap, not a correctness gap).
- `runner.py` gains a new dependency edge on `phase_resolver` — accepted
  coupling toward the single source of truth.

## Affected modules

core/skills (phase_resolver, budget_guard, clarify_config, runner,
plugin_gen), core/phases (intake), core/agents (intake-triage, shared
completion-signal block), klc-plugin (skills/run, regenerated agents),
config (clarify.yml).

## Lessons learned

- A "single source of truth" module is only as good as its test
  coverage of every real input it's supposed to unify — `phase_resolver`
  was architecturally correct on day one but functionally wrong for 5 of
  14 phases until a test parametrized over every `phases.yml` id (not
  just the 2-3 ids convenient to write a test against) caught it.
- A prompt-driven orchestration step (no Python driver, by design) needs
  the same rigor a code review would apply to a conditional: "stop" and
  "do X then continue" must be two textually distinct branches, not one
  branch with an "e.g." — ambiguity in sequencing prose is a real bug
  class, not just a style nit.
- Two independent review passes (codex external + a fresh subagent) each
  found a real, non-overlapping HIGH-severity bug that internal
  self-review missed. Neither pass alone would have caught both — worth
  keeping both review sources for changes of this shape (new
  cross-cutting infrastructure with a prompt-driven component).
