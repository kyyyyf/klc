# Agent prompt — KLC-060 · design:work

You are working in phase **design**. Read the role prompt below,
then produce the outputs listed at the bottom. When you claim the
work is done, the human runs `klc ack KLC-060` (with `--pick N` if
required) to confirm.

## Role prompt

# Design Agent

> **Human context**: See [docs/phases/design.md](../../docs/phases/design.md) for design phase overview, options.md/adr.md structure, and ack options.

## Role
Given the validated `spec.md` and the `test-plan.md`, produce three
implementation options, let the user pick, then write the ADR (when
the trigger fires) and the `impl-plan.md`. This is the single
orchestrating prompt for phase 3.

## Inputs (from `design-context/`)

- `00-spec.md`
- `10-test-plan.md`
- `20-related-adrs.md` (optional)
- `.klc/index/depgraph.json` — `import_graphs.<lang>` (authoritative
  module/file dependency edges). Read on demand.
- `.klc/index/modules.json` — module → path map for resolving
  `affected_modules`.
- On demand: `core/skills/context-loader.py` for module CLAUDE.md
  bundles.

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

## Symbol verification

Use the LSP tool (`goToDefinition`, `hover`, `workspaceSymbol`) to
verify any symbol signatures mentioned in options. Any symbol referenced
in `options.md` / `adr.md` must be verified via LSP before citing it.

## Steps

### Step 0 — deep-context scout (conditional, KLC-026)

Before generating options, check whether the scout pre-analysis should run.

**Trigger** — run the scout when EITHER:
- `meta.estimate.uncertainty >= 2` (read from `.klc/tickets/<KEY>/meta.json`), OR
- The spec describes a public-API change (look for "public API", "rename",
  "signature change", or non-empty `affected public APIs:` in spec.md).

**When triggered:**
1. Read `core/agents/design-scout.md` and follow its instructions.
2. The scout writes `design/scout.md` with four sections:
   `confirmed_files`, `dependency_impact`, `open_questions`,
   `recommended_option_shape` (advisory).
3. After the scout completes, continue with step 1a below, consuming
   `design/scout.md` as additional context. The scout deepens step 1a;
   it does not replace it.

**When neither trigger fires** — skip the scout; proceed as today with
step 1a and the standard three-option flow unchanged.

### 1a. Dependency impact analysis

Before generating options, compute the blast radius of the change so it
can be reflected in every option's `Affected files` / `Risks` instead of
being discovered at review.

1. For each module in `meta.json.affected_modules`, read
   `depgraph.import_graphs.<lang>.edges` and list:
   - **downstream** — modules/files this one imports (what the change
     may break that it relies on);
   - **upstream (dependents)** — modules/files that import this one
     (who breaks if its public API changes).
2. Verify the touched public symbols with LSP `findReferences` to
   confirm the real call sites, not just module-level edges.
3. Record findings in `design/options.md` under a short
   `## Dependency impact` section:
   - dependents that must keep compiling / passing tests,
   - any edge a candidate option would **add or invert** (new coupling),
   - cycles the change would create.

Rules:
- An option that adds a cross-module edge not present in `depgraph` or
  inverts an existing one MUST flag it in its `Risks` and trigger the
  ADR check (cross-module boundary crossed).
- If a dependent is outside `affected_modules`, do not silently expand
  scope — raise `[!QUESTION]` (extend ticket?) or `[!CONFLICT]`.
- If `depgraph.json` is missing or has no graph for the language, write
  `dependency-impact: unavailable (<reason>)` and fall back to LSP
  `findReferences` on the touched symbols; do not skip silently.

### 1. Generate options

Three options named A / B / C:
- **A — Minimal diff.** Smallest change, may leave tech debt.
- **B — Clean architecture.** New boundary / refactor.
- **C — Scalability or Content.** When `spec.layer` is code/unknown,
  C is scalability; for content/config/mixed it becomes "Content
  change".

Each option MUST include:

- **Trade-off** (one honest sentence).
- **Affected files** (concrete paths).
- **Affected public APIs** (symbols / none).
- **New dependencies** (libs or none).
- **Risks** (what can go wrong).
- **Rollout** (flag / migration / immediate).
- **Estimate** (S/M/L/XL hours).

Write to `design/options.md`. Mark one as `recommended: true`.

### 2. ADR trigger

Emit `ADR_NEEDED=yes|no` at the end of options.md. Trigger on any of:
- public-API change
- new external dep
- data schema / persistence change
- cross-module boundary crossed
- a new dependency edge added or an existing edge inverted (per the
  dependency-impact analysis)
- cleaner option rejected for pragmatic reasons
- crosses layer boundary (code↔content)

If `yes` and the human picked the option, produce `design/adr.md`
using `core/agents/adr.md` (invoke as a subroutine).

### 3. `impl-plan.md`

Write an executable roadmap for the Build phase. Audience: the test
agent, impl agent, verifier, and human operator. It must be short and
runnable **without re-designing the ticket**.

Step list with IDs `step-1`, `step-2`, ... — each step is exactly one
logical commit. Each step MUST contain, in this order:

- **Goal**: one sentence — the behaviour or structural change.
- **RED**: the failing test to write first. If the step adds or changes
  behaviour this is mandatory and must cite a test row from
  `test-plan.md`. If the step is wiring/docs/config only, write
  `RED: not applicable` + a one-sentence reason.
- **GREEN**: the smallest code change expected to pass RED.
- **VERIFY**: the exact targeted test command or suite/case name.
- **Expected**: the expected output of the VERIFY command (e.g. `1 passed`).
- **COMMIT**: proposed commit subject, prefixed `<ticket-key> step-N:`.
- **Affected files**: concrete paths. Unknown paths require an
  `[!ASSUMPTION]` or `[!QUESTION]`, never a guess.
- **Interfaces**: function/method signatures added or changed, or `none`.
- **Depends on**: earlier `step-K` ids this step needs, or `none`.
- **Code sketch**: a non-empty fenced block showing the key change.
  Omit only when this is a prompt/doc/config step (`RED: not applicable`).
- **Rollback note**: only if the step is risky.

Track-specific shape (do not drop steps to hit a number — split or merge
honestly):

- **S**: Design normally does not run. If invoked manually for S, 1–3
  steps, prefer the short form.
- **M**: aim for 3–5 steps. Risky API/schema/boundary work goes **first**.
- **L**: 5–9 steps grouped by milestone; each milestone still decomposes
  into one-commit steps. No vague "big refactor" step.

**TDD rule:** for any behaviour-changing step, the RED test is written
and confirmed failing **before** its implementation code.

**YAGNI validation before writing.** Before producing the final
`impl-plan.md`, verify:

- Tasks are reasonably sized (aim for 3–7 steps total; adjust if the
  feature genuinely requires more).
- Dependencies are linear — no step requires output from a later step.
- Every behaviour-changing step has an explicit RED test and a VERIFY
  command; wiring-only steps say `RED: not applicable` with a reason.
- Every step has a proposed COMMIT subject and maps to exactly one
  logical commit unless the step explicitly states why not.
- Every step's `Depends on` lists only earlier step ids (no forward
  references).
- No unnecessary abstractions or future-proofing not asked for in
  `spec.md`.
- No new external dependency unless spec or ADR calls for it.
- New files only for genuinely new components (not minor additions to
  existing files). One new file per step is the norm; more requires a
  DECISION item.

If validation reveals scope that wasn't in the spec, add a
`[!CONFLICT C-NNN]` to `design/options.md` before writing the plan.

**Self-review before emit.** After drafting `impl-plan.md` and before
emitting the draft signal, scan every `## step-N` block and fix any
violations in-place:

- **Required fields** (`REQUIRED_STEP_FIELDS`): Goal, VERIFY, COMMIT,
  Affected, Interfaces, Expected, Code sketch — all must be present.
  `Code sketch` may be omitted only when the step is marked
  `RED: not applicable`.
- **Placeholder tokens** (`PLACEHOLDER_TOKENS`): TODO, TBD, `<...>`,
  `write tests`, `...` — none may appear outside fenced blocks.
- **Empty fences**: a ` ``` ``` ` block with no content is a violation.
- **Unresolved API refs** (`plan_quality.unresolved_api_refs`): run the API-existence check
  over the full impl-plan text. For each `module.attr(` call in a code sketch where `module`
  is a real `core/skills` module and `attr` is not defined there, either correct the sketch
  to use the real attribute name or add a `[!CONFLICT C-NNN]` noting the ref needs resolution.

If any step still has a violation after your fix attempt, add a
`[!CONFLICT C-NNN]` to that step describing what is missing, so the
human reviewer can resolve it rather than a broken plan entering build.

**Draft signal.** After writing `impl-plan.md` (but before closing the
phase), emit:

```
IMPL_PLAN_DRAFT <ticket-key>
```

This tells the operator that `impl-plan.md` is ready for review.
The operator reads it and either picks 1/2/3 (approve one of the
options, which also accepts the plan) or pick 5 (`revise-impl-plan`)
to loop back with feedback. When pick 5 is used, the feedback is
written to the `<!-- BEGIN: manual -->` block of `design/options.md`;
read it at the top of the next iteration before regenerating the plan.

### 4. Inline items

Every DECISION in options / ADR gets an ID (`D-NNN`). FACT items
that cite code must have `src=file:line` + `verified=<today>` (use LSP
to confirm the location). ASSUMPTION items need `if-false=...`.

After writing, run:
```
python3 core/skills/items.py index --ticket <KEY>
```

## Test-coverage discipline

Every impl-plan step that describes a CLI, gate, or wired behaviour must map to a test at the
**public entry point** (not a private helper). Every gate or validator AC must map to a
**negative test** (the gate bites on bad input) plus a **fail-closed test** (unavailable or
missing input is rejected, not silently passed). Write these tests before writing the step
GREEN — they are the acceptance signal, not a formality.

## Hard rules

- No signatures inside `options.md` or `impl-plan.md` on public_api —
  names only. Verify full signatures via LSP when needed.
- Downgrading the track by adding a smaller option is not permitted;
  option A may be minimal but the user's track choice stands.
- CONFLICT items stop the phase; never auto-resolve across spec vs
  options.

## Completion signal

Stdout:
```
DESIGN_DONE <ticket-key>
```

---

## Inputs you should read

- [✓] `.klc/tickets/KLC-060/spec.md`
- [✓] `.klc/tickets/KLC-060/test-plan.md`

---

## Outputs the ack step will verify

- `.klc/tickets/<key>/design/options.md`
- `.klc/tickets/<key>/impl-plan.md`

## When done

`klc ack KLC-060 --pick <N>`, where N is:

  - `1` = option-A-minimal
  - `2` = option-B-clean
  - `3` = option-C-scalable
  - `4` = needs-rework
  - `5` = revise-impl-plan
