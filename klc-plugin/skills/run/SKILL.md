---
name: klc-run
description: >
  Run a klc ticket through its lifecycle without a human re-reading
  every phase's artifacts. Resolves each phase via phase_resolver,
  dispatches inline (XS) or to a klc-<phase> subagent (S/M/L), throttles
  advancement through `klc ack --auto` + `klc next`. Actively runs the
  mandatory intake clarify pass (AskUserQuestion) rather than parking
  on it, and stops for the human at every other human-interaction point
  (ambiguous pick, blocking question, budget hard breach, repeated
  phase failure).
---

# /klc:run — ticket orchestrator (KLC-052)

## Role

You are the **main agent**, acting as orchestrator. This is a
prompt-driven loop, not a hidden Python driver (C-001) — every decision
below reads from `phase_resolver`, `phases.yml`, and the phase's own
structured completion signal. You do not invent state; you ask the
tools.

Usage: `/klc:run <TICKET-KEY>`

## The loop

Repeat until STOP or archived:

1. **Status.** Run `python3 scripts/klc status <KEY> --json`. Parse
   `phase_id`, `state`, `track`.
2. **Archived?** If `state == "archived"`: report DONE, exit the loop.
3. **Resolve.** Call `core.skills.phase_resolver.resolve_phase(<KEY>,
   phase_id, executor="task")` (import from `core/skills`, `PROJECT_ROOT`
   already set) — you are always the Task-tool executor, never the headless
   one, so this is the one place that decides the card mode; nowhere else in
   this loop hardcodes `"dispatch"` or `"paste"` (C-001). This gives you
   `runs_inline`, `agent_type`, `model`, `interactive`, `card_mode`,
   `card_path`.
4. **Interactive gate.** If `resolved.interactive` is true, this is a
   human-interaction point — but the two flavors need different
   handling, and only one of them means "just stop":
   - **Clarify gate** (`meta.json:clarify_required` is true on the
     `intake` phase): this is **not** a place to silently park and
     wait — AC-7/AC-8 require the clarify pass to always fire, in this
     turn, before you do anything else. Follow
     `core/agents/intake-triage.md`'s "Interactive clarify (main-loop
     only)" section now: issue ONE `AskUserQuestion` (batch, default)
     or one question at a time (serial) per
     `clarify_config.load_clarify_style()`, using the triage's
     `missing_info[]`. Write the answers back into `raw.md` under the
     `intake-notes` markers, re-run `route_heuristic.classify()`,
     update `meta.json`, and clear `clarify_required`. Only after that
     is done, go back to step 1 and re-resolve from a clean state —
     never dispatch discovery in the same breath as clearing the gate,
     and never treat "resolved.interactive" here as license to stop
     without asking.
   - **Any other interactive gate** (an `:ack-needed` phase whose pick
     is irreducibly human — a design option, a manual sign-off, a
     merge approval): **stop here for real** and hand control to the
     human. Never guess a pick on their behalf, never dispatch past
     this point (C-005 — this is exactly what `runner.py` parks on
     headlessly; in-client, you are the park — but the clarify gate
     above is the one case where "you are the park" means "you do the
     asking," not "you do nothing").
5. **Work state — dispatch.** If `state == "work"`:
   a. Prepare and gate the dispatch. Unless `resolved.runs_inline` (in
      which case go straight to b): re-render the card in
      `resolved.card_mode` right before dispatching — a card `klc
      next`/`klc step` last wrote is `paste` mode and stale by
      definition; you need a fresh `dispatch`-mode card. Call
      `core.skills.artefacts.render_card(<KEY>, phase_id, meta,
      step=<step, build only>, mode=resolved.card_mode)` and keep the
      result as `card_render` (its `est_tokens`/`card_bytes`). Then the
      advisory budget check, on THAT card's own number:
      `core.skills.budget_guard.gate_card_dispatch(track,
      card_render.est_tokens if card_render else None)` — a render
      failure passes `None`, which the gate treats as a hard breach
      (fail-closed), never as zero. If `verdict.hard_breach`: surface
      a blocking question and STOP (do not dispatch).
   b. If `resolved.runs_inline` (XS fast-track): do the phase's work
      yourself, inline, in this loop. Then construct the same
      completion-signal JSON a subagent would emit (see below).
   c. Otherwise: read the text of the card rendered in (a) and
      `Task(subagent_type=resolved.agent_type, prompt=<the card's
      text>)`. Take the subagent's returned text as `result`. After
      parsing in (d), call
      `core.skills.run_signal.record_signal_tokens(signal, <KEY>,
      phase_id, card_render)` — a `signal.tokens` block records a
      `signal`-sourced attempt; its absence falls back to the card's
      own `estimated` attempt from (a).
   d. Parse: `core.skills.run_signal.parse_signal(result, expected_phase
      =phase_id)`.
      - If `None` (unparseable / missing keys / phase mismatch / bad
        enum): this is a **failure**. Track a per-phase failure
        counter for this loop invocation (starts at 0, not persisted
        across `/klc:run` calls). Increment it, then check
        `core.skills.run_signal.should_retry(failure_count)`:
        - `True` (first failure): re-dispatch the SAME phase once.
        - `False` (second consecutive failure): STOP, surface the raw
          `result` to the human, do not advance, do not retry again.
      - If parsed: reset the failure counter for this phase.
   e. **Blocking questions — STOP.** If `signal.blocking_questions` is
      non-empty: surface them to the human and stop. Do not paraphrase
      them away.
   f. **Post-build step ledger pass.** Build phase only, and only when 5d
      parsed the signal as `done` and 5e found no blocking questions: run
      `python3 core/skills/step_ledger.py --ticket <KEY>` from the project
      root. It re-runs each impl-plan step's VERIFY command, derives that
      step's touched files from its own commits, writes `build/progress.md`
      and refreshes the machine-made `## Evidence` rows. Report any `red`,
      `scope-violation` or `unverified` verdict to the human verbatim. This
      is a report, not a decision: you still ack in step 6 exactly as
      before, and `build.verify_steps: false` skips this sub-step entirely.
      Never run it on a retried dispatch or a parked one — a build that is
      not finished has nothing to verify. This CLI invocation is a
      DELIBERATE extra VERIFY execution beyond the one `klc ack`'s own
      `can_complete_build` call makes internally (which shares one
      per-ack Verdict cache between its own arms, KLC-114 review round
      1) — the two calls do not share a cache with each other, so each
      step's VERIFY runs once here AND once more inside `ack`. This is
      intentional (Q-001): the operator sees the verdicts BEFORE deciding
      whether to ack at all, which a cache spanning two separate process
      invocations cannot offer without persisting the re-run output to
      disk between them.
6. **Advance.** On a clean `signal.signal == "done"` with no blocking
   questions: run `klc ack <KEY> --auto`.
   - Non-zero exit (ambiguous pick / gate paused / scope conflict):
     STOP, surface the CLI's stderr verbatim — do not guess a pick.
     When `ack --auto` paused on a dirty `advisory` signal (KLC-117),
     the stderr line names the signal but not its content: read
     `<ticket-dir>/<phase-id>/ack-advisories.json` and report its
     `high` and `medium` records to the human, with a bare count of
     the rest. Never parse the summary line or the phase-history note
     for advisory detail — the JSON is the machine-readable source and
     the note is a pointer to it.
   - Zero exit: if the ticket is now in an `:ack` state (rather than
     already advanced to the next phase's `:work` — `apply_ack`
     resolves an unambiguous forward pick directly), run `klc next
     <KEY>` to complete the transition.
7. **Loop.** Go to step 1.

## Completion signal you must emit for inline (XS) work

When you did the phase's work yourself (step 5b), end your own
response with the same fenced JSON contract every `klc-<phase>`
subagent uses (see `core/agents/*.md`'s "Completion signal
(orchestrator)" section):

```json
{"phase":"<phase-id>","signal":"done","artifacts":["path/relative/to/ticket/dir.md"],"blocking_questions":[],"next_action":"ack"}
```

## Stop conditions (never silently work around these)

- `resolved.interactive` on a **non-clarify** gate — an `:ack-needed`
  phase whose pick is irreducibly human (step 4, second bullet). The
  clarify gate is the one interactive case that is NOT a stop
  condition by itself — you actively run it (step 4, first bullet)
  and only stop afterward if some other condition below also fires.
- `ack --auto` non-zero exit — pick_required / gate dirty / ambiguous
  (step 6).
- Non-empty `blocking_questions` (step 5e).
- Budget hard breach (step 5a).
- Second consecutive phase failure (step 5d).

Any of these hands control back to the human. Report exactly which
condition fired and why — never guess a pick, never invent an answer
to a blocking question, never dispatch past a non-clarify interactive
gate without stopping, and never skip the mandatory clarify pass by
treating it as an ordinary stop condition.
