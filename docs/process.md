# klc process

Concise reference. Authoritative source for phases and transitions
is [`config/phases.yml`](../config/phases.yml).

---

## Principles

1. **Kanban, not waterfall.** Work flows through phases by pull.
2. **Agents draft, humans gate.** LLMs produce every artefact; humans
   confirm at obligatory picks. Spec is sealed after discovery ack.
3. **Multi-dimensional estimate → track.** 4 axes (complexity /
   uncertainty / risk / manual), each 0–3. Total → XS / S / M / L.
   Downgrades forbidden; upgrades always allowed.
4. **Facts tagged in every artefact.** `[!FACT src=…]`,
   `[!ASSUMPTION if-false=…]`, `[!DECISION D-NNN]`. Enables
   retrospective verification and cuts hallucination.
5. **Short XS path.** XS skips acceptance-test-plan, design, and
   observe. Uses discovery-lite instead of full discovery.
   One build agent call + review-lite.
6. **Conditional phases.** `observe` runs only when `risk_tags` contains
   `user-facing`, `data`, `security`, or `migration`. `learn` runs only
   when rework occurred or budgets were overrun. Discovery agents set
   `risk_tags` in meta.json; skipped phases are recorded in
   `phase_history` with `event=skipped`.

---

## Tracks

| Track | Score | Typical scope            |
|-------|-------|--------------------------|
| XS    | 0–2   | one-line change or typo  |
| S     | 3–5   | local fix / refactor     |
| M     | 6–8   | feature in one module    |
| L     | 9–12  | cross-module / new dep   |

Guard invariants: any axis = 3 floors at M; uncertainty = 3 + total ≥ 7 forces L.

---

## Phase map

All phases defined in `config/phases.yml`. `klc next` advances from
`:ack` → next phase's `:work`. `klc ack --pick N` closes `:ack-needed`.

| Phase id               | Tracks      | Agent prompt                      | Picks at `:ack-needed`                                    |
|------------------------|-------------|-----------------------------------|------------------------------------------------------------|
| `intake`               | XS S M L    | `core/agents/intake.md`           | 1 = confirm                                                |
| `discovery`            | XS S M L    | `core/agents/discovery.md`        | 1 = approve · 2 = needs-rework                            |
| `acceptance-test-plan` | S M L       | `core/agents/test-planner.md`     | 1 = approve · 2 = needs-rework                            |
| `design`               | M L         | `core/agents/design.md`           | 1 = option-A · 2 = option-B · 3 = option-C · 4 = rework · 5 = revise-impl-plan |
| `detailed-test-plan`   | M L         | `core/agents/test-planner.md`     | 1 = approve · 2 = needs-rework                            |
| `xs-build`             | XS          | `core/agents/xs-fasttrack.md`     | 1 = approve · 2 = upgrade-to-S                            |
| `build`                | S M L       | `core/agents/impl.md`             | 1 = approve                                                |
| `review-lite`          | XS          | `core/agents/review-lite.md`      | 1 = approve · 2 = request-changes · 3 = override          |
| `review`               | S M L       | `core/agents/review.md`           | 1 = approve · 2 = request-changes (→ build:work)          |
| `manual`               | M L         | `core/agents/manual-check.md`     | 1 = passed · 2 = failed (→ build:work)                    |
| `integrate`            | XS S M L    | _(checklist, no agent)_           | 1 = merged                                                 |
| `observe`              | S M L       | _(monitoring checklist)_          | 1 = clean · 2 = regression · 3 = rollback                 |
| `learn`                | XS S M L    | `core/agents/retrospective.md`    | 1 = archive · 2 = extract-to-CLAUDE.md                    |

**XS path**: intake → discovery → xs-build → review-lite → integrate → learn

**S path**: intake → discovery → acceptance-test-plan → build → review → integrate → observe → learn

**M path**: intake → discovery → acceptance-test-plan → design → detailed-test-plan → build → review → manual → integrate → observe → learn

---

## Verbs

```
klc intake <key> [--kind feature|bug|tech] "<desc>"
klc status <key>               # vertical path view
klc next   <key>               # :ack → next phase :work
klc ack    <key> [--pick N]    # :ack-needed → :ack
klc ship   <key> [--pick N]    # ack + next in one step
klc step   <key> <N>           # regenerate minimal TDD step card (build only)
klc jump   <phase> <key> [--yes]   # cross-cut to any phase :work
klc abort  <key>               # cancel :work → previous :ack
```

Operational (non-phase):
```
klc board                      # kanban view
klc doctor                     # install health check
klc metrics <key>              # per-ticket JSON
klc metrics --rollup           # 30-day aggregate
klc init [--scan-only|--auto|--finalize]
klc update [--regen] [--force]
klc jira-sync [--dry-run]      # flush Jira push queue
klc jira-sync status           # queue size + oldest entry age
```

---

## Human gates

Every phase with `pick_required: true` is a gate — the human must
choose a pick before `next` proceeds.

| Gate              | Phase                          | Tracks  |
|-------------------|--------------------------------|---------|
| confirm intake    | `intake:ack-needed`            | all     |
| pull-ready        | `discovery:ack-needed`         | XS S M L |
| accept test plan  | `acceptance-test-plan:ack-needed` | S M L |
| direction         | `design:ack-needed`            | M L     |
| detail test plan  | `detailed-test-plan:ack-needed`| M L     |
| xs build          | `xs-build:ack-needed`          | XS      |
| build             | `build:ack-needed`             | S M L   |
| review-lite       | `review-lite:ack-needed`       | XS      |
| merge approval    | `review:ack-needed`            | S M L   |
| manual check      | `manual:ack-needed`            | M L     |
| observe outcome   | `observe:ack-needed`           | S M L   |
| learn outcome     | `learn:ack-needed`             | all     |

---

## Build phase — TDD loop (S / M / L)

`build:work` is a multi-step loop driven by `impl-plan.md`.

1. **Test agent** (`core/agents/test.md`) writes a failing test for
   the current step.
2. **Impl agent** (`core/agents/impl.md`) makes it pass. Uses
   LSP (`workspaceSymbol`, `goToDefinition`, `findReferences`) for
   all symbol navigation — no speculative file reads.
   Each step gets a minimal card via `klc step <key> N` (Goals + ACs
   + current step only — no full spec/plan context).
3. Repeat until all steps are green, then `klc ack <key> --pick 1`.

**`build-log.md`** is an append-only journal maintained by the impl
agent: one entry per iteration with outcome (`green | red | blocked`)
and notes. The reviewer reads it to understand what was attempted; the
retrospective agent uses it for metrics.

**Review signal rule.** `APPROVED` / `REVIEW_LITE_PASS` means "this
iteration found zero issues". If the reviewer finds and fixes
something during a pass, it emits `CHANGES REQUESTED` /
`REVIEW_LITE_CRITICAL` — so the operator can schedule another pass to
confirm the fix didn't introduce new problems.

Budget counters in `meta.json:budgets` (limits in `config/budgets.yml`):

| Counter               | Limit | Bumped when                              |
|-----------------------|-------|------------------------------------------|
| `red_test_fix_attempts` | 3   | test still red after impl change         |
| `mutation_fix_attempts` | 3   | mutation score below threshold           |
| `regenerate_impl_plan`  | 3   | human requests a fresh plan              |
| `rework_review_cycles`  | 3   | review sends back to build               |
| `xs_fix_attempts`       | 3   | XS fast-track: test still failing        |

Hitting a limit writes `meta.json:blocked_reason` and halts. Agent
emits `[!QUESTION]` or `[!CONFLICT]`; human decides next action.

---

## XS fast-track

Single-agent path for trivial changes (score 0–2).

1. `klc intake <key> --kind bug "<desc>"` → `intake:ack-needed`
2. `klc ack <key> --pick 1` → `discovery:work`
3. Run `discovery` agent. Produces `spec.md` with ACs and
   `affected_modules`. This is where the XS score is confirmed.
4. `klc ack <key> --pick 1` → `xs-build:work`
5. Run `xs-fasttrack` agent with prompt card at
   `.klc/tickets/<key>/xs-build/_prompt.md`.
   Agent: reads `spec.md` + `raw.md` + root `CLAUDE.md` → locates
   code via LSP → writes fix + test → commits → emits `XS_IMPL_DONE`
   or `XS_BLOCKED`.
6. `klc ack <key> --pick 1` → `review-lite:work`
7. Run `review-lite` agent. Blocks only on CRITICAL (security, API
   break, data corruption). Emits `REVIEW_LITE_PASS` or
   `REVIEW_LITE_CRITICAL`.
8. `klc ack <key> --pick 1` (approve) or `--pick 2` (request-changes
   → back to `xs-build:work`) → `integrate:work` → `learn`.

If scope expands beyond `affected_modules`: agent emits `XS_BLOCKED`,
human uses `klc jump acceptance-test-plan:work --yes` to upgrade to S/M
(discovery is already done).

---

## Indexing loop

Run once per project, then automatically on each commit via the
pre-commit hook.

```bash
klc init --scan-only   # deterministic: file_scanner + dep_graph + .last-run
klc init --auto        # + inventory / decompose / docgen agents (LLM)
klc init --finalize    # record HEAD after running agents manually
klc update             # git diff since .last-run → stale.json
klc update --regen     # regenerate skeleton CLAUDE.md for stale modules
```

`klc intake` warns when `stale.json` has stale modules.
`hooks/pre-commit` runs `update.py` automatically (deterministic,
~1–3 s). No LLM in the hot path.

---

## Discovery context (S / M / L)

Context bundle loaded by `write_prompt_card` when entering
`discovery:work`:

| File | Content |
|------|---------|
| `00-raw.md` | raw description + intake-agent notes |
| `10-root-CLAUDE.md` | project invariants |
| `20-module-docs.md` | CLAUDE.md of up to 3 modules with highest keyword overlap with `raw.md` |
| `40-related.md` | recent tickets with matching kind / modules |
| `50-external-docs.md` | optional external doc pointers |

Symbols are **not** pre-loaded. Agent uses LSP `workspaceSymbol` on
demand — cheaper than a static dump and always current.

---

## Inline item format

All artefacts use a common markup for facts, assumptions, decisions,
and open questions. Items are indexed by `core/skills/items.py` into
`.index.json` and checked by the consistency gate before integrate.

```
[!FACT F-001]       src=path/to/file:42  verified=2026-05-21
[!ASSUMPTION A-001] if-false=rollback-to-option-B
[!DECISION D-001]   owner=impl-agent  date=2026-05-21  refs=step-3
[!QUESTION Q-001]   blocks=discovery
[!CONSTRAINT C-001] source=security-review
[!CONFLICT C-001]   (scope creep / infeasible option / broken assumption)
```

`CONFLICT` always halts the agent and requires human resolution.
`QUESTION` with `blocks=<phase>` prevents phase advance until answered.

---

## Token telemetry & budget guard

### Budget guard

Before dispatching any agent call, `runner.py` estimates the prompt size
(`len(chars) // 4` tokens) and applies two tiers from `config/budgets.yml`:

| Track | Soft (warn) | Hard (block) |
|-------|-------------|--------------|
| XS    | 6 000       | 12 000       |
| S     | 15 000      | 30 000       |
| M     | 45 000      | 90 000       |
| L     | 150 000     | 300 000      |

- **Soft limit** — warning on stderr, run proceeds normally.
- **Hard limit** — dispatch refused; `[!QUESTION] context too large` written
  to the output file. No model call is made.

### Telemetry

After every successful agent run, token counts are written to
`meta.json:metrics.tokens.<phase_id>`:

```json
"metrics": {
  "tokens": {
    "discovery-lite": {"in": 1200, "out": 340, "cache_hit": 0},
    "build":          {"in": 4800, "out": 920, "cache_hit": 1100}
  }
}
```

When `claude --output-format json` is used, actual usage is parsed from the
response envelope. Otherwise token counts are estimated from character length.

### Rollup

```bash
klc metrics --rollup   # aggregates tokens_by_phase per track across all tickets
```

Output includes `avg_in`, `avg_out`, `avg_cache_hit`, `samples` per phase per
track, written to `.klc/knowledge/process-metrics.json`.

---

## Review cascade

Before launching the full multi-agent review, `review_cascade.py` runs a
three-step pipeline to decide the review depth:

```
scope_delta → scan_sentinels → classify_tier → CascadeDecision
```

| Signal | Result |
|--------|--------|
| Scope expansion (unplanned modules) | Full review |
| Any sentinel hit | Full review |
| Any `critical` or `core` tier file | Full review |
| All `peripheral` + no drift + no sentinels | **Cheap review** (single Sonnet agent) |

**Cheap review** dispatches one focused reviewer instead of the full
sub-agent pipeline. Controlled by `config/reviewers.yml`:

```yaml
cascade:
  enabled: true
  peripheral_max_files: 20   # fallback to full if diff is very large
```

`review-cheap` role in `models.yml` controls the model used for cheap
review. `per_track.S.review-cheap: local-simple` uses Haiku for S-track.

---

## Conditional phases

Some phases are skipped automatically based on `meta.json` fields set by
discovery agents. Skipped phases are recorded in `phase_history` as
`event: skipped` with the reason.

| Phase     | Runs when                                                              |
|-----------|------------------------------------------------------------------------|
| `observe` | `meta.risk_tags` contains any of: `user-facing`, `data`, `security`, `migration` |
| `learn`   | `meta.rework_count` has any value > 0, OR `meta.regression_observed == 1`, OR `meta.budgets` has any overrun |

Discovery and discovery-lite agents must set `risk_tags: [...]` in
`meta.json`. Set to `[]` for pure tooling/config changes with no
user-visible impact.

**Expression language** (used in `phases.yml condition:` field):
```
meta.<path> in ['v1', 'v2']      # true if value or any list element matches
meta.<path> not in ['v1', 'v2']
meta.<path> > N
meta.<path> >= N
meta.<path> == N
meta.<path> any_overrun           # true if any dict value > 0
<expr> OR <expr>                  # short-circuit or
```

---

## Signals that escalate to human

- `CONFLICT` item in any artefact.
- Budget counter at limit (`blocked_reason` in `meta.json`).
- `rework_count[phase] ≥ 3` — recommend escalation to lead.
- Scope creep: diff touches modules outside `affected_modules`.
- XS: `XS_BLOCKED` signal from xs-fasttrack or review-lite.

---

## Jira sync

One-way push: klc → Jira. The filesystem and git remain the source of
truth for ticket content. Jira is a mirror of the current phase.

### Setup

1. Copy `config/jira.yml` to `.klc/config/jira.yml` in the project.
2. Set `sync.enabled: true` and fill in `rest.base_url`.
3. Export `JIRA_TOKEN` (Personal Access Token). For basic auth also
   export the variable named in `rest.auth_user_env`.
4. Adjust `phase_to_status` to match your Jira workflow's status names.

```yaml
# .klc/config/jira.yml
url_template: "https://jira.example.com/browse/{key}"
sync:
  enabled: true
  transport: rest        # rest | mcp
  rest:
    base_url: "https://jira.example.com"
    auth_env: JIRA_TOKEN
  phase_to_status:
    build: "In Progress"
    review: "In Review"
    archived: "Done"
```

For `transport: mcp`, set `sync.mcp.url` to the HTTP endpoint of a
running `mcp-atlassian` instance.

### How it works

Every `lifecycle.set_state()` call (triggered by `klc next`, `ack`,
`jump`, `abort`) attempts to push the new phase to Jira immediately
with a short timeout (default 2 s).

- **Success** → `meta.json:jira_last_sync` updated; Jira reflects the
  new status within seconds.
- **Failure / timeout** → event queued in `.klc/jira-queue.jsonl`;
  no klc command is blocked.

The queue is drained opportunistically — no background processes:
- Any `klc` command checks and drains the queue on startup.
- The `pre-commit` git hook drains on every commit.
- Explicit flush: `klc jira-sync`.

Deduplication: only the latest phase per ticket is sent on flush.

### Commands

```
klc jira-sync              flush queue, verbose
klc jira-sync --dry-run    show what would be sent
klc jira-sync --quiet      flush silently (used internally)
klc jira-sync status       queue size and oldest entry age
```

`klc doctor` reports queue health: warns if >100 entries or oldest
entry is >7 days old.

---

## Repository layout

```
klc/                           # framework repo
  config/
    phases.yml                 # state machine (source of truth)
    models.yml                 # model → role-slot mapping
    reviewers.yml              # review gates, mutation threshold
    budgets.yml                # (optional) override budget limits
    ticket-id.yml              # regex for ticket keys
    jira.yml                   # Jira url_template + sync config (transport, mapping)
  core/
    agents/                    # LLM prompt files
    phases/                    # command implementations (*.py)
    skills/                    # supporting tools
    templates/                 # Jinja2 templates
    rules/                     # ast-grep rules
  profiles/
    generic/                   # default profile
    ue/                        # Unreal Engine profile
  hooks/
    pre-commit                 # consistency check + update.py + jira-sync drain
  scripts/
    klc                        # dispatcher
    init.py / update.py        # indexing loop
    review.py                  # multi-agent review orchestrator
  docs/                        # this directory
  tests/smoke.py

<project>/
  .klc/
    config/                    # per-project overrides
    index/                     # structural.json, depgraph.json, stale.json, …
    tickets/<KEY>/             # spec.md, impl-plan.md, meta.json, …
    tickets/archive/<KEY>/     # finished tickets
    knowledge/                 # reviewer-allowlist, process-metrics, few-shot
    logs/
  CLAUDE.md                    # root, generated by docgen
  <module>/CLAUDE.md           # per-module, generated
```
