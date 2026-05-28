# Agent prompt — KLC-007 · design:work

Ticket: **KLC-007** · track: **M** · kind: **tech**

You are working in phase **design**. Read the role prompt below,
then produce the outputs listed at the bottom. When you claim the
work is done, the human runs `klc ack KLC-007` (with `--pick N` if
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
- On demand: `core/skills/context-loader.py` for module CLAUDE.md
  bundles.

## Symbol verification

Use the LSP tool (`goToDefinition`, `hover`, `workspaceSymbol`) to
verify any symbol signatures mentioned in options. Any symbol referenced
in `options.md` / `adr.md` must be verified via LSP before citing it.

## Steps

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
- cleaner option rejected for pragmatic reasons
- crosses layer boundary (code↔content)

If `yes` and the human picked the option, produce `design/adr.md`
using `core/agents/adr.md` (invoke as a subroutine).

### 3. `impl-plan.md`

Step list with IDs `[step-1]`, `[step-2]`, ... — each step is one
logical commit. Per step:

- Description
- Affected files
- Expected tests (from test-plan.md)
- Rollback note (only if the step is risky)

Short form for S track (≤ 10 lines, single step). Full form
otherwise.

**YAGNI validation before writing.** Before producing the final
`impl-plan.md`, verify:

- Tasks are reasonably sized (aim for 3–7 steps total; adjust if the
  feature genuinely requires more).
- Dependencies are linear — no step requires output from a later step.
- No unnecessary abstractions or future-proofing not asked for in
  `spec.md`.
- No new external dependency unless spec or ADR calls for it.
- New files only for genuinely new components (not minor additions to
  existing files). One new file per step is the norm; more requires a
  DECISION item.

If validation reveals scope that wasn't in the spec, add a
`[!CONFLICT C-NNN]` to `design/options.md` before writing the plan.

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

- [✓] `.klc/tickets/KLC-007/spec.md`
- [✓] `.klc/tickets/KLC-007/test-plan.md`

---

## Outputs the ack step will verify

- `.klc/tickets/<key>/design/options.md`
- `.klc/tickets/<key>/impl-plan.md`

## When done

`klc ack KLC-007 --pick <N>`, where N is:

  - `1` = option-A-minimal
  - `2` = option-B-clean
  - `3` = option-C-scalable
  - `4` = needs-rework
  - `5` = revise-impl-plan
