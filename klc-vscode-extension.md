# klc · VS Code extension — Adapter A + file watch

Concept note, not a spec. Describes the minimum UI that removes the
"two terminals" friction without binding the design to any particular
LLM client or to the exact shape of klc's commands. Command names are
placeholders — the framework's own CLI is the authority and will
change; this document deliberately avoids echoing specific invocations.

## Problem

When a person drives klc through a ticket, two windows are open in
parallel:

1. A terminal running klc's lifecycle commands. It prints what phase
   the ticket is in, what happens next, and embedded instructions for
   the LLM step (bundle paths, which prompt template to use, which
   file to write, which completion line to print).
2. An LLM chat (or headless agent) that receives the copy-pasted
   prompt and writes the phase's artefact.

The person is the integration layer. They copy completion hints out
of the terminal, paste them into the agent, run the agent, observe
that the artefact appeared, switch back to the terminal, and run the
next lifecycle command. Every round-trip has a transcription step.

The extension described here collapses that transcription step into
one surface. It does not automate the agent. It does not hide the
terminal. It removes the need for a **second terminal** whose only
role is to ferry structured text the user already owns.

## Scope

This note describes **two pieces** only:

- **Adapter A** — "clipboard adapter". Surface the LLM step to the
  person, hand them a ready-to-paste prompt with every input path
  pre-resolved. Do not spawn agents, do not talk to any vendor API.
- **File watch** — observe `.klc/` and the workspace, detect that a
  phase's expected artefact was produced, surface the next lifecycle
  step without asking the person to re-type anything.

Everything else (running an agent as a subprocess, native klc agent
host, multi-ticket kanban, module graph) is out of scope. Those can
be bolted on later without reworking the foundation.

## Principles

- **klc remains the source of truth.** The extension never reimplements
  lifecycle rules. If klc exposes a machine-readable "what's next"
  endpoint, the extension reads it and renders. If klc changes, the
  extension adapts by re-reading — not by re-coding.
- **Agent-agnostic.** The extension never assumes a specific LLM
  client. The default (and only guaranteed) integration path for the
  LLM step is `copy to clipboard`. Any further integration is opt-in.
- **No hidden actions.** The extension may run klc commands only on
  an explicit click. It never advances lifecycle, never mutates
  ticket state, never sends anything to an LLM "on behalf of" the
  person.
- **Terminal is first-class.** Commands that klc prescribes run in
  VS Code's integrated terminal, in full view. The extension is a
  navigator, not a wrapper around stdout.
- **Fail safe, not silent.** If anything is unclear — stale state,
  missing file, unknown phase — surface it as a warning in the tree
  view; do not pretend to know.

## Data contract (what klc needs to expose)

The extension consumes a small, stable contract from klc. Exact
command names and JSON keys are for klc's author to decide; the
shape below is illustrative.

1. **"What's next for this ticket"** — a machine-readable description
   of the ticket's current state, available on demand. It includes:
   - the ticket key and current phase;
   - an optional next **shell step** (a lifecycle command, its working
     directory, a short explanation of what it will do, and a list of
     preconditions with pass/fail labels);
   - an optional next **LLM step** (the prompt template path, the
     input bundle path, the expected output file(s), the completion
     signal the agent should print or the file the agent should
     write to indicate "done");
   - any blockers (unresolved questions in spec, failing guards, etc.).

2. **A rendered prompt** — given the next LLM step, klc can produce
   the full prompt text with every relative path resolved to an
   absolute one and every placeholder substituted. The extension
   requests this text and places it in the clipboard; it never
   assembles prompts from templates itself.

3. **Event log** — a plain append-only file under `.klc/` where
   both lifecycle commands and agents record what happened: phase
   transitions, exit codes, completion signals, artefact paths
   touched. The extension watches this file to refresh its view.

The contract is small enough that klc can add it without changing
any phase script internals. The extension treats missing fields as
"nothing to show", not as errors.

## UI surfaces

### Status bar (one line)

One status-bar item, left-aligned:

```
$(klc) <ticket-key> · <phase> · next: <short hint>
```

- One active ticket — show it directly.
- Multiple active — show a count; click opens a quick-pick list.
- Last command failed — background turns red, text becomes a brief
  failure hint. Click reveals the output panel.
- No tickets at all — item hidden.

The status bar never *acts*. It is a reminder and a jump-off point.

### Explorer panel "klc · Next Steps"

A tree view that groups actions by ticket. Two levels deep. Top
level is the ticket; children are the next available steps.

```
▼ <ticket-key>   <phase>   [ready | blocked | waiting]
    Next LLM step: <short description>
        template : <path to prompt template>
        bundle   : <path to input bundle directory>
        output   : <file the agent is expected to produce>
      [ copy prompt ]   [ open bundle ]   [ open template ]

    When the agent finishes:
      Next shell step: <what it does in one line>
      [ copy command ]   [ run in terminal ]
      preconditions:
        ✓ <label>
        ✓ <label>
        ⚠ <label that isn't satisfied yet>

▼ Project health
    <warnings that aren't tied to one ticket>
```

Important details:

- **"copy prompt"** is the only interaction with the LLM. The
  extension calls klc to render the full prompt (with resolved paths),
  puts the result on the clipboard, shows a toast "prompt copied —
  paste into your agent". That's it.
- **"run in terminal"** opens (or focuses) the integrated terminal,
  pastes the command, and presses nothing. The person decides when
  to press Enter. This deliberate friction prevents the extension
  from driving lifecycle on its own.
- **"copy command"** is the clipboard variant, for users who prefer
  typing themselves.
- **preconditions** are rendered as-is from the klc endpoint. The
  extension does not interpret them.
- **blockers** (e.g. unresolved questions in a spec) are rendered
  above the action buttons and grey the buttons out when they would
  advance through a blocker.

### Notifications (sparse)

Toasts only on meaningful transitions:

- Phase changed (e.g. after a successful klc command).
- Agent completion detected (file appeared or completion signal
  logged).
- Last run failed.

Each toast offers exactly the actions from the tree view (copy /
run). No modal dialogs; nothing is blocking.

## File watch

The extension keeps a small set of watchers running as long as a
workspace is open. None of them trigger writes — they only refresh
the view.

1. **`.klc/tickets/*/meta.json`** — phase changes and metadata drift.
   On change, the extension re-queries klc for "what's next" on that
   ticket and refreshes its node in the tree view.

2. **Ticket artefact files** under `.klc/tickets/<key>/` — whatever
   files the current phase lists as "expected output". When one of
   those files is written (or updated), the extension interprets
   this as "the agent likely produced it" and surfaces the next
   shell step.

3. **Event log** under `.klc/` — an append-only file the framework
   writes to. Each entry has at minimum a timestamp, an event kind
   (`phase-transition`, `command-exit`, `agent-completion`,
   `warning`), a ticket key, and a short payload. The extension
   tails this file; new lines drive status-bar updates and toasts.

4. **`.klc/index/*.json`** — the project-wide indices (inventory,
   modules, per-module hash). On change, `Project health` is
   refreshed; individual ticket nodes are not affected unless klc
   tells the extension otherwise.

Watcher behaviour is conservative:

- Re-queries are debounced (≈250 ms) so a burst of writes from a
  single agent run doesn't thrash the UI.
- A file event never mutates state directly. It triggers a re-query
  of klc, and klc's answer drives the view.
- If klc is slow or missing, the extension shows the last known
  state and a dimmed "stale since <time>" hint — it never guesses.

## End-to-end flow

A typical ticket advance, without a second terminal:

1. Extension displays the ticket node with a ready LLM step and the
   prompt pre-rendered. Status bar shows the same hint.
2. Person clicks **copy prompt**. A toast confirms the clipboard was
   written. The person pastes it into whichever LLM client they use
   — a chat window in a browser, a headless CLI in a shell pane, a
   local model's UI. The extension doesn't care which.
3. The LLM writes the expected artefact to the path the prompt
   embedded. The file appears under `.klc/tickets/<key>/…` (or the
   working tree, for build phases).
4. File watch picks up the write. The extension re-queries klc.
   The node updates: the LLM-step button is greyed out, the shell
   step (the lifecycle command that consumes the artefact) becomes
   active.
5. Person clicks **run in terminal**. The integrated terminal opens,
   the command is pasted, the person reads it and presses Enter.
   They see stdout in the same pane.
6. Event log picks up the exit. The extension re-queries klc. Phase
   advances. The node re-populates with the next round's steps.
7. Repeat until the ticket is in a terminal phase.

No second terminal; no copy-pasting out of stdout; no vendor API;
no manual phase bookkeeping.

## Non-goals

- Running the agent. Adapter A never spawns any LLM process. A
  future "Adapter B" can add a configurable `agent.yml` that binds
  a CLI to a "run agent" button — that is an extension of this
  design, not a replacement.
- Editing ticket artefacts in a bespoke UI. Specs, test plans,
  design notes, retrospectives are plain markdown. They are edited
  in the normal editor.
- Parsing LLM output. The extension never reads what the agent
  wrote inside an artefact. It only observes that an artefact was
  produced and trusts klc to validate its contents on the next
  lifecycle step.
- Hiding the terminal. Nothing is wrapped, decorated, or intercepted.
  The terminal remains the canonical place where framework output
  is read.
- Taking hard-to-reverse actions. No advancing phases, no deleting
  files, no pushing to remotes, no network I/O beyond what klc
  itself does.

## Minimum viable implementation

Four pieces, in order:

1. **A tiny read-only query to klc** that returns "what's next" for
   one ticket. Sufficient shape: current phase, next shell command
   (if any), next LLM step (if any), blockers. Everything else on
   the UI is derived from this.
2. **Status-bar item** reading that query for the currently active
   ticket (heuristic: the one most recently modified in
   `.klc/tickets/`; the person can switch via quick-pick).
3. **Tree view** with `copy prompt`, `open bundle`, `copy command`,
   `run in terminal`. No icons, no custom styling — default VS Code
   `TreeDataProvider` is enough for MVP.
4. **Two watchers**: `.klc/tickets/*/meta.json` and the event log.
   Both debounce and re-query. That alone covers phase transitions
   and command-exit surfacing; artefact watch can be added in a
   follow-up once the first two are stable.

This set is small enough to ship in one week and already removes the
second terminal. Everything else — health panel, multi-ticket kanban,
agent adapters B and C — sits on top of the same data contract and
same UI surfaces without restructuring.

## What this note intentionally leaves open

- **Exact klc command names** — this document describes the
  contract, not its CLI surface. The framework's maintainer chooses
  invocations; the extension adapts.
- **Event-log schema** — any line-oriented, append-only format works.
  JSONL is a sensible default; a simpler `<ISO> <kind> <payload>`
  also works. The extension should tolerate unknown kinds.
- **Prompt template rendering** — responsibility of klc. The
  extension only receives the rendered text.
- **Bundle directory layout** — responsibility of klc. The extension
  only opens whatever path klc points at.
- **Multi-project / multi-ticket ergonomics** — left for a later
  iteration; the data contract above already supports it but the
  UI only needs to handle one at a time on day one.
