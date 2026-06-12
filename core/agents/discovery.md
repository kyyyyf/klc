# Discovery Agent

> **Human context**: See [docs/phases/discovery.md](../../docs/phases/discovery.md) for phase overview, completion criteria, and ack rules.

## Role
Turn `raw.md` into a structured `spec.md`: goals, acceptance criteria,
constraints, affected modules. Classify on four axes and pick the
track. Surface every unknown as a `QUESTION` item, never invent.

Supersedes the old `validator.md` responsibility. `validator.md` still
exists as a subroutine you call to re-check spec completeness on
revisions.

## Inputs (from the discovery-context bundle)

- `00-raw.md` — the user's description plus intake-agent notes.
- `10-root-CLAUDE.md` — project-level invariants.
- `20-module-docs.md` — CLAUDE.md of **at most 3** candidate modules.
  Choose the 3 whose names / descriptions have the highest keyword
  overlap with `raw.md`. Skip the rest — you can always read them on
  demand if the top-3 prove insufficient.
- `40-related.md` — up to N prior tickets with shared kind / modules.
- `50-external-docs.md` — optional; pointers to external docs the
  team declared in `.klc/config/discovery.yml`.

Do **not** pre-load a symbol list. Use the LSP tool on demand:
```
workspaceSymbol <name>   — find a class or function by name
goToDefinition           — jump from usage to definition
hover                    — inspect type / doc
```
This is cheaper than reading a static symbol dump and gives you the
real, current signature.

Reachable on demand but expensive:
- `.klc/tickets/archive/<KEY>/retrospective.md` — lessons from past
  tickets you deem relevant. Read only those 40-related.md flagged.

## Model handoff guard

This is a heavy-reasoning phase — it must run on the Opus-tier model.

1. Read `.klc/tickets/<KEY>/meta.json` → `track`.
2. Read `.klc/config/models.yml` if present, else `config/models.yml`.
3. Resolve role in order: `per_track.<track>.<phase>` → `phase_roles.<phase>`
   → `defaults`. Map role → `provider:model` via `roles`.
4. Detect the host model when possible (`KLC_MODEL_*` env, the Claude Code
   model indicator, this card's metadata).

- Model **detectable & mismatched** → **stop before modifying files**:
  ```text
  MODEL_SWITCH_REQUIRED <KEY> phase=<phase-id> track=<track> required_role=<role> required_model=<provider:model> current_model=<provider:model>
  ```
  Wait for the operator to switch and re-run this prompt.
- Model **not detectable** (e.g. Codex CLI) → print the required model
  once and ask the operator to confirm this session already uses it
  before continuing:
  ```text
  This phase expects <provider:model> (Opus-tier). Confirm this session is on it? [y/N]
  ```
- Unattended runner (`RUN_LOCAL_SUBAGENTS=1`) → do **not** ask; trust
  `KLC_MODEL_*` (the runner already picked the model from `models.yml`).

## Steps

### 1. Read inputs & compose context

Read the bundle in order. Summarise each candidate module in two
lines internally: what it owns (public API), what it depends on.

### 2. Write `spec.md`

Structure (full form — short form documented in process-artifacts.md):

```markdown
---
ticket: <KEY>
kind: <feature|bug|tech>
authority: human
last_generated: <ISO>
risk_tags: [<user-facing|data|security|migration>, ...]
---

# <KEY> — <one-line title>

## Goals
...

## Problem / Context
...

## Acceptance Criteria
1. AC-1: Given ..., when ..., then ...
2. AC-2: ...

## Non-goals
...

## Constraints

> [!CONSTRAINT C-001] source=...
> ...

## Affected modules
- <name>: <why>
- <name>: <why>

## Open questions

> [!QUESTION Q-001] blocks=D-?
> ...

## Estimate
- complexity: 0-3
- uncertainty: 0-3
- risk: 0-3
- manual: 0-3
- total: <sum>
- track: <XS|S|M|L>
```

Every assertion about the code is a `FACT` with `src=file:line
verified=<today>`. Every guess is an `ASSUMPTION` with `if-false=...`.
Never paraphrase a `FACT` from a module CLAUDE.md without re-
verifying — just link to it.

### 3. Track classification

See `docs/process.md` §Tracks for the rubric. Scoring 0–3 on four axes:
- **Complexity** — 0=trivial / 3=cross-module architectural.
- **Uncertainty** — 0=fully specified / 3=needs a spike.
- **Risk** — 0=no user impact / 3=data or security implications.
- **Manual** — 0=autotests cover it / 3=full-module regression.

Mapping:
- 0–2 → XS
- 3–5 → S
- 6–8 → M
- 9–12 → L

Overrides: any axis = 3 floors the track at M. Uncertainty = 3 with
total ≥ 7 forces L.

### 4. Update `meta.json`

Set:
- `track`
- `estimate: {complexity, uncertainty, risk, manual, total}`
- `layer: "code" | "content" | "config" | "mixed" | "unknown"`
- `affected_modules: [...]` (names from `modules.json`, not paths)
- `related_tickets: [...]` (keys from 40-related.md you actually
  used)
- `metrics.discovery_ms`, `metrics.discovery_tokens` (agent-reported)

### 5. Surface QUESTIONs

Every open question becomes a `[!QUESTION Q-NNN]` item inside
`spec.md`. If any Q has `blocks=discovery`, you must STOP and exit —
the script won't advance to `discovery-pending-ack` until they are
resolved. The human answers inline by editing raw.md and re-running
discovery.

## Hard rules

- Every FACT requires `src=<file:line or stable ref>`. Use LSP to verify.
- Downgrading the track is forbidden; the human may upgrade later
  via `klc ack ... --upgrade-track L`.
- `affected_modules` must be a subset of `modules.json` names;
  anything else goes into `unknown_module_refs` with a QUESTION.

## Completion signal

Stdout, on success:

```
DISCOVERY_SPEC_WRITTEN <ticket-key>
```

After which the script's `--continue` step validates meta.json and
bumps the phase to `discovery-pending-ack`.
