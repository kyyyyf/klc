---
name: klc-go
description: Move the ticket one step forward, or until a phase. Use when the user wants to advance a klc ticket.
argument-hint: <TICKET-ID> [options]
allowed-tools: Bash, Task, AskUserQuestion
---

# /klc:go — Move the ticket one step forward, or until a phase

Run `klc go $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.

## Driving a ticket to integrate (`klc go <KEY> --until integrate`)

You are the main agent. `klc go` decides every move; you only dispatch phase
agents and ask the human. This one skill is the whole orchestrator loop.

1. Run `klc go <KEY> --until integrate`. Exit 0: the ticket reached
   `integrate:work`. Tell the human: merge the branch per the project's rules,
   then run `klc go <KEY> --pick 1`, then run `klc go` again for the remaining
   phases; stop. Exit 1: show stderr verbatim and stop.
2. Exit 2: the stop line carries exactly ONE reason. Check them in this order.
   - **Guardrail** (`integrate`, `cap`, `budget-ceiling`): STOP, show the line verbatim.
   - **Clarify** (`clarify needed`): go to step 3a.
   - **Pick** (`klc go <KEY> --pick N`): STOP and ask the human, with the options
     shown. Never guess a pick. For an advisory stop, read
     `<ticket-dir>/advisories.json`, report the phase's `high` and `medium`
     records plus a bare count of the rest; never parse the phase-history note.
   - **Build not green** (`build is not green`): go to step 3 with phase `build`.
   - **Agent card** (`<phase>:work needs the agent`): go to step 3.
   - Anything else: STOP, show the line verbatim.
3. Dispatch the phase agent.
   a. **Clarify gate** (the `clarify needed` stop; phase `intake`, `meta.json:clarify_required` true):
      follow `core/agents/intake-triage.md` "Interactive clarify (main-loop
      only)" now: ask via `AskUserQuestion` per
      `clarify_config.load_clarify_style()`, write the answers into `raw.md`,
      re-run `route_heuristic.classify()`, clear `clarify_required`, run
      `klc go <KEY> --pick 1`, then go to step 1. Never dispatch discovery in the same breath.
   b. Resolve: `core.skills.phase_resolver.resolve_phase(<KEY>, phase_id,
      executor="task")` gives `runs_inline`, `agent_type`, `card_mode`. The mode
      is decided there and nowhere else. An agent stop of `klc go` also prints
      one line `dispatch: agent=<klc-…> model=<alias> card=<path>`; its `model` is
      the models.yml role for the ticket's TRACK and is the one you pass below.
   c. Unless inline, re-render the card with `core.skills.artefacts.render_card(
      <KEY>, phase_id, meta, step=<build only>, mode=resolved.card_mode)`
      (`klc go` wrote a stale paste card). Show the warn-only
      `core.skills.budget_guard.real_spend_warning(track, ticket=<KEY>)` line, if any.
   d. If `resolved.runs_inline` (XS): do the work yourself and end with the
      completion-signal JSON. Otherwise
      `Task(subagent_type=<agent>, model=<model>, prompt=<card text>)` with the
      `agent` and `model` of the `dispatch:` line (never omit `model=`: the
      agent file's frontmatter `model:` is not relied on), then `core.skills.run_signal.record_signal_tokens`.
   e. Parse with `core.skills.run_signal.parse_signal(result, expected_phase=
      phase_id)`. `None` is a failure: retry the same phase once
      (`should_retry`); on the second failure STOP and show the raw result.
   f. Non-empty `blocking_questions`: STOP and show them unchanged.
   g. Build only: run `klc step verify <KEY> N` for each step missing or stale in
      `build/steps.json` and report failures verbatim (not after a retry).
   h. Review: the agent gets `--diff recorded` and plans three layers. If the
      plan refuses over the cap, STOP; never pass `--over-cap` yourself.
4. Go to step 1 (`klc go` acks the finished phase).

Rules: never merge and never push (`integrate:work` is where the human merges);
every reviewer is a fresh subagent (not a fork) and may not write to git; never
guess a pick, invent an answer, or skip the clarify pass.
