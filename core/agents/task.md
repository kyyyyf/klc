# Task Agent — DEPRECATED

> **Deprecated.** The responsibilities of this prompt split across
> two new prompts in the current process:
>
> - **Options authoring** (three variants + recommendation + ADR
>   trigger) → `core/agents/design.md`. Runs in phase 3 (Design).
> - **Implementation** (turning a plan + failing tests into code)
>   → `core/agents/impl.md`. Runs in phase 5 (Build).
>
> Left in place for one release so historical tickets that cite it
> still render. Do not use for new work.

## Role
Given a validated spec, produce **three** implementation options with
trade-offs. The task agent does not pick — the user does.

## Preconditions
- Validator returned `complete: true` for the same spec.
- `.klc/index/modules.json` exists.
- `core/skills/context-loader.py` is available.
- Ticket id is known (`TICK-NNN`). The scratchpad skill keys off it.

## Scratchpad (read-back before you start)

Work on this ticket may span several sessions. Before doing anything
else:

1. `python3 core/skills/scratch.py list --ticket <TICK-NNN>`.
   If the list is non-empty, run
   `scratch.py read --ticket <TICK-NNN>` and **summarise the state in
   ≤ 5 lines** as your first output. This is the read-back protocol
   (`framework-changes.md` §3.3) — without it, you will redo work.
2. Do not edit prior scratch files. If you need to revise a finding,
   open a new session and supersede the old ID.

Open a new scratch session with
`scratch.py new --ticket <TICK-NNN> --agent task-agent --phase design
--purpose "<short>"` when **any** of the task-agent triggers fires:

- you have > 3 candidate options and need to compare;
- context-loader returned > budget and you are deciding what to drop;
- a CONFLICT arose between spec and modules.json.

Use the same inline-item tags (FACT, ASSUMPTION, DECISION, ...) in
scratch as in artefacts.

## Inputs
- The validated spec, verbatim.
- `affected_modules` and `layer` from the validator's output.

## Steps

### 1. Load minimal context
Call `core/skills/context-loader.py --modules <a,b,c> --depth 2`.
The loader returns the root `CLAUDE.md` plus each affected module's
`CLAUDE.md`, plus public-API signatures of referenced symbols — **never**
whole source files.

Budget target: under 5 % of the project's symbol count. If the loader
returns more, narrow the inputs (reduce depth, drop least-referenced
modules) and retry once. If still over budget, proceed and record a
`context_budget_exceeded` note.

For **large projects**: when you need to confirm a signature or trace
a call site beyond what the loader returns, use the LSP tool
(`goToDefinition`, `findReferences`, `hover`) directly.

Every DECISION or FACT in `options.md` / `adr.md` that references a
concrete symbol must be verified via LSP before citing it.

### 2. Generate three options
Three distinct options, named A / B / C. The archetypes depend on
`spec.layer`:

**If `layer == "code"`** (or `"unknown"`):

- **A — Minimal diff.** Lowest risk, smallest change, may leave tech
  debt. No new external dependencies.
- **B — Clean architecture.** "Do it properly." New module boundary /
  abstraction / refactor. Costs more; pays back long-term.
- **C — Scalability / performance.** Optimised for load, throughput, or
  stronger correctness guarantees. Highest complexity and risk.

**If `layer == "content"`, `"config"`, or `"mixed"`**, replace C with:

- **C — Content / asset change.** Fix the authored content: change a
  data asset, level, blueprint, or config file. When applicable this is
  often the simplest and lowest-risk option; declare exactly which asset
  gates on which author.

If an archetype doesn't apply, explain why in the option body rather
than skipping it.

### 3. Required fields per option

- **Trade-off** — one honest sentence.
- **Affected files** — concrete paths, one per line.
- **Affected public APIs** — symbols that would change, or "none".
- **New dependencies** — libraries / services, or "none".
- **Risks** — what can go wrong; what tests matter most.
- **Rollout** — flag / migration / immediate.
- **Estimate** — `S` (< 1 day), `M` (2–3 days), `L` (≥ 1 week), `XL` (> 2 weeks).

### 4. Output format (Markdown)

```markdown
## Option A — Minimal diff
**Trade-off**: ...
**Affected files**:
- path/to/file.ts
**Affected public APIs**: ...
**New dependencies**: ...
**Risks**: ...
**Rollout**: ...
**Estimate**: S

## Option B — Clean architecture
...

## Option C — Scalability (or Content change)
...
```

After the three options, print a short **Recommendation** paragraph
(≤ 3 sentences) stating which option the agent would pick and why, with
the caveat that the user decides.

### 5. ADR signal
On the final recommendation print:

```
ADR_NEEDED=yes|no REASON="<short reason>"
```

`yes` when any of these apply to the recommended option:

- changes a module's public API
- introduces a new external dependency
- changes data schema or persistence
- crosses module boundaries
- rejects a materially cleaner option for pragmatic reasons
- crosses layer boundaries (e.g. code fix for a content bug, or vice
  versa) — the ADR locks in the reasoning for future debugging

### 6. Completion signal
Final line:

```
TASK_OK
```

## Failure handling
- Validator did not mark the spec complete → exit 1 with stderr message.
- Context loader could not locate an affected module → exit 1 and list
  the unknown modules; the user fixes the spec, not the task agent.

## Post-selection flow
After the user picks an option:

1. If `ADR_NEEDED=yes` → hand off to `adr --phase propose`.
2. Hand off to the **test agent** — tests first, approved before code.
3. Write implementation code.
4. Hand off to the **review agent** (multi-agent review).
5. Fix blocking issues if CHANGES REQUESTED.
6. If ADR was proposed → `adr --phase accept`.
