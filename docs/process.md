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
   `user-facing`, `data`, `security`, or `migration`. `learn` always runs
   for M/L (ADR-accept + terse or full retro); for XS/S it runs only when
   rework occurred or budgets were overrun. Discovery agents set `risk_tags`
   in meta.json; skipped phases are recorded in `phase_history` with
   `event=skipped`.

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
| `intake`               | XS S M L    | `core/agents/intake.md`           | 1 = confirm-route · 2 = force-full-discovery · 3 = force-xs-skip (XS only) |
| `discovery-lite`       | XS S        | `core/agents/discovery-lite.md`   | 1 = approve · 2 = needs-rework · 3 = upgrade-to-full      |
| `discovery`            | M L         | `core/agents/discovery.md`        | 1 = approve · 2 = needs-rework                            |
| `acceptance-test-plan` | M L         | `core/agents/test-planner.md`     | 1 = approve · 2 = needs-rework                            |
| `design`               | M L         | `core/agents/design.md`           | 1 = option-A · 2 = option-B · 3 = option-C · 4 = rework · 5 = revise-impl-plan |
| `detailed-test-plan`   | L           | `core/agents/test-planner.md`     | 1 = approve · 2 = needs-rework (M: tests folded into impl-plan steps) |
| `xs-build`             | XS          | `core/agents/xs-fasttrack.md`     | 1 = approve · 2 = upgrade-to-S                            |
| `build`                | S M L       | `core/agents/impl.md`             | 1 = approve                                                |
| `review-lite`          | XS          | `core/agents/review-lite.md`      | 1 = approve · 2 = request-changes · 3 = override          |
| `review`               | S M L       | `core/agents/review.md`           | 1 = approve · 2 = request-changes (→ build:work)          |
| `manual`               | M L         | `core/agents/manual-check.md`     | 1 = passed · 2 = failed (→ build:work)                    |
| `integrate`            | XS S M L    | _(checklist, no agent)_           | 1 = merged                                                 |
| `observe`              | S M L       | _(monitoring checklist)_          | 1 = clean · 2 = regression · 3 = rollback                 |
| `learn`                | XS S M L    | `core/agents/retrospective.md`    | 1 = archive · 2 = extract-to-CLAUDE.md                    |

**XS path**: intake → discovery-lite → xs-build → review-lite → integrate → learn

**S path**: intake → discovery-lite (spec+test-plan+impl-plan) → build → review → integrate → observe → learn

**M path**: intake → discovery → acceptance-test-plan → design (impl-plan w/ tests) → build → review → manual → integrate → observe → learn

---

## Verbs

```
klc intake <key> [--kind feature|bug|tech] "<desc>"
klc status <key>               # vertical path view
klc next   <key>               # :ack → next phase :work
klc ack    <key> [--pick N]    # :ack-needed → :ack
klc ship   <key> [--pick N]    # ack + next in one step
klc step   <key> <N>           # regenerate minimal TDD step card (build only)
klc work   <key>               # read-only: the next action (card/outputs/verify)
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
klc scope-fix <key> (--modules a,b,c | --add a,b | --remove a,b) [--reason ...]
```

### Post-archive scope correction — `klc scope-fix`

`meta.affected_modules` records a ticket's planning slice. During work it is
corrected at `ack` (each `ack` runs a `state_tx` that commits and CAS-pushes the
ticket subtree). Once a ticket is **archived** no further `ack` runs, so an
edit to the slice — for example dropping a scope-guard entry that was widened
only temporarily — has no `state_tx` to sweep it and would otherwise need a
manual `klc-state` commit + push.

`klc scope-fix` is the first-class, durable path. It edits `affected_modules`
inside the **same** `acquire_lock → state_tx` envelope every state write uses,
so feature-ON the correction is committed and CAS-pushed to the bound upstream
immediately (a peer sees it with no ack), and feature-OFF it is a plain local
write (no lock, no git).

**Archived-only.** `scope-fix` refuses any non-archived ticket (it prints a
message pointing you back to `ack`). `affected_modules` is enforcement input —
it drives the scope-expansion hard-fail at `ack` — so while a ticket is live the
slice must be corrected at `ack` (update `affected_modules` rather than fighting
it), where the change rides `ack`'s own `state_tx` and holder discipline. Only
after archive is there no `ack` left to sweep the edit; that is the gap this verb
fills. Because an archived ticket holds no holder, `scope-fix` — like `jira sync
--apply` — takes no holder authorization; the archived gate is what closes the
authority hole. Three mutually-exclusive modes:

- `--modules a,b,c` — replace the slice with exactly this set.
- `--add a,b` — union the listed modules into the slice.
- `--remove a,b` — drop the listed modules from the slice.

Malformed lists (an empty entry from a stray/trailing comma) are rejected before
any write; module names unknown to `modules.json` are a non-fatal advisory (the
index may be absent or stale). Every correction is recorded as a `scope-fix`
entry in `meta.phase_history`.

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

Mechanical pre-conditions block `ack` before the human pick is offered:
- **discovery-lite ack (S)**: spec self-review clean; ≥2 approaches + pick in `options-lite.md`;
  `impl-plan.md` required and must pass `impl_plan_violations()` (plan-completeness gate).
- **design ack (M/L)**: `design/options.md` and `impl-plan.md` must exist and be non-empty;
  `impl-plan.md` must pass the plan-completeness gate.
- **build ack (S/M/L)**: `build-log.md` must exist, be non-empty, and contain a
  `## Evidence` section with at least one non-empty fenced block (command + pasted output).

Agent-side discipline (KLC-037): the design agent and test-planner (M detailed mode)
self-review `impl-plan.md` before emitting their completion signal — scanning every
`## step-N` for missing `REQUIRED_STEP_FIELDS`, placeholder tokens, and empty fences,
and fixing violations inline. This acts as a first line of defence before the
mechanical gate runs at ack.

---

## Build phase — TDD loop (S / M / L)

`build:work` is a multi-step loop driven by `impl-plan.md`.

1. **Test agent** (`core/agents/test.md`) writes a failing test for
   the current step.
2. **Impl agent** (`core/agents/impl.md`) makes it pass. Uses
   LSP (`workspaceSymbol`, `goToDefinition`, `findReferences`) for
   all symbol navigation — no speculative file reads.
   Each step gets a dependency-resolved brief via `klc task-brief <key> N`
   (Goals + ACs + current step body + dependency interfaces/COMMIT surfaces
   — no foreign step bodies). The brief is written to
   `build/step-N-brief.md`; a skeleton `step-N-impl-report.md` is also
   scaffolded for the impl agent to fill.
   For a lightweight minimal card (Goals + ACs + current step only),
   use `klc step <key> N` instead.
   By default the step card **references** `core/agents/impl.md` by
   path instead of embedding it (~7.5 KB saved per step). For paste-only
   workflows without filesystem access, set `KLC_CARD_INLINE=1` to
   embed the full role prompt.
3. **Per-step review** (M/L always; S only with `risk_tags`; XS never): after
   each green step, an independent reviewer reads only the step package
   (`step-N-brief.md` + `step-N-impl-report.md` + step diff) and routes
   findings by severity. CRITICAL/HIGH are blocking — a fix subagent is
   dispatched and the step is re-reviewed (capped at `PER_STEP_REREVIEW_CAP`
   attempts, then blocked). MEDIUM/LOW are logged to `step-N-review.md`
   without blocking. The per-step review runs as a post-green hook inside
   the `klc build-run` orchestrator (`core/skills/per_step_review.py`).
4. Repeat until all steps are green, then `klc ack <key> --pick 1`.

**`build-log.md`** is an append-only journal maintained by the impl
agent: one entry per iteration with outcome (`green | red | blocked`)
and notes. Before `klc ack`, the impl agent must append an `## Evidence`
section (see `core/agents/impl.md`) — `build:ack` is mechanically blocked
without a non-empty fenced block under it. The reviewer reads the full log
to understand what was attempted; the retrospective agent uses it for metrics.

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
   Intake prints `route=XS confidence=<low|medium|high>` (deterministic
   heuristic from `route_heuristic.py`). The track is a **provisional floor**.
   On a short, low/medium-confidence ticket intake recommends the cheap
   `intake-triage` agent (or `--pick 2` to force full discovery) — a short
   description means under-specified, not necessarily simple.
2. `klc ack <key> --pick 1` (confirm-route) → `discovery-lite:work`
3. Run `discovery-lite` agent. Produces compact `spec.md` (Goals, AC,
   Affected, Estimate). Uses `[!ASSUMPTION]` not blocking `[!QUESTION]`.
   This is where the XS score is confirmed (`estimate.total ≤ 2`).
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
| `00-raw.md` | raw description + intake notes |
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
    "discovery-lite": {"in": 1200, "out": 340, "cache_hit": 0,    "source": "provider"},
    "build":          {"in": 4800, "out": 920, "cache_hit": 0,    "source": "estimated"}
  }
}
```

`source` is `"provider"` when parsed from a real `usage` block in the
claude CLI JSON envelope, `"estimated"` when derived from `len(text)//4`.
`cache_hit` is always `0` for `estimated` source. The rollup reports
`source_counts: {provider: N, estimated: M}` per phase so you can see
how many measurements are exact vs approximate.

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
| Scope expansion (unplanned modules) or unknown files | Full review |
| Scope comparison unavailable (`skipped`) | Full review (fail-closed) |
| Classifier returns no file tiers | Full review (fail-closed) |
| Any sentinel hit | Full review |
| Any `critical` or `core` tier file | Full review |
| Peripheral files count > `peripheral_max_files` | Full review |
| Total changed lines > `peripheral_max_lines` | Full review |
| All `peripheral` + no drift + no sentinels + within size limits | **Cheap review** (single focused agent) |

**Fail-closed:** the cascade defaults to full review when it cannot prove
peripheral. "Unavailable" ≠ "no risk". Only proven peripheral + no
signals → cheap review.

The **cheap reason string** always includes the diff size:
`peripheral diff, no sentinels, no scope drift → cheap review (N files, M lines)`.

**Cheap review** dispatches `core/agents/review/cheap.md` — correctness,
test coverage, spec alignment only (no security/architecture depth).
Controlled by `config/reviewers.yml`:

```yaml
cascade:
  enabled: true
  peripheral_max_files: 20   # fallback to full when too many peripheral files
  peripheral_max_lines: 500  # fallback to full when diff volume is too large
```

`review-cheap` role in `models.yml` controls the model used for cheap
review. `per_track.S.review-cheap: local-simple` uses Haiku for S-track.

The review report frontmatter carries `review_depth` (`cheap` | `lite` | `full`),
`full_review_offered`, and `full_review_declined` to feed the retro and
`cheap_escape_rate` rollup in `process-metrics.json`.

### External reviewer (default-on for S/M/L)

`external_reviewer.enabled: true` in `config/reviewers.yml` means the external
reviewer runs for all S/M/L tickets. It runs on both cheap and full cascade
paths. Skip conditions (first match wins):
1. `--no-external` flag
2. `meta.review.skip_external: true`
3. `external_reviewer.api_key_env` not set in the environment (graceful; `klc doctor` warns)

Controlled by `config/reviewers.yml`:

```yaml
external_reviewer:
  enabled:      true
  min_track:    S       # XS never hits the external reviewer
  api_key_env:  OPENAI_API_KEY
```

---

## Conditional phases

Some phases are skipped automatically based on `meta.json` fields set by
discovery agents. Skipped phases are recorded in `phase_history` as
`event: skipped` with the reason.

| Phase     | Runs when                                                              |
|-----------|------------------------------------------------------------------------|
| `observe` | `meta.risk_tags` contains any of: `user-facing`, `data`, `security`, `migration` |
| `learn`   | Always for M/L. For XS/S: when `meta.rework_count` > 0, OR `meta.regression_observed == 1`, OR `meta.budgets` any overrun |

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
- Scope creep: diff touches modules outside `affected_modules`, or touches
  files outside all known module prefixes (`unknown_files` in scope_delta).
  At `review:ack`, missing `modules.json` is a hard failure — run
  `klc init --scan-only` to build it.
- XS: `XS_BLOCKED` signal from xs-fasttrack or review-lite.

---

## Jira integration

Two layers of Jira integration are available:

- **Legacy push** (`jira-sync` command, `mode: mirror`): auto-pushes phase→status
  on every `ack`. Suitable when klc is the only driver and Jira is a pure mirror.
- **`klc jira` commands** (KLC-020+): read-only status, GitLab artefact links,
  intake dup-check. Explicit sync and reconcile in KLC-021/022.

### `klc jira` — integration commands (KLC-020+)

```bash
klc jira status <KEY>                           # read-only: klc phase vs Jira status
klc jira sync <KEY> --dry-run                   # show what links would be added/updated
klc jira sync <KEY> --apply                     # upsert GitLab artefact links in Jira
klc jira reconcile <KEY> push                   # push klc phase to Jira explicitly
klc jira reconcile <KEY> pull --to <phase>      # move klc to match Jira (KLC-022)
klc jira reconcile <KEY> force-pull --to <phase> --reason "..." # skip missing inputs
```

#### Managed mode (KLC-021+)

Set `mode: managed` in `.klc/config/jira.yml` to enable interactive divergence
detection. In managed mode:

- klc does **not** auto-push on every `ack`. Push is manual via
  `klc jira sync --apply` or `klc jira reconcile push`.
- At `ack`/`next`, if Jira diverged from the last known state, klc prompts
  **inline**:

```
[jira] KLC-021: klc moved to review:work, Jira is "In Progress".
  1) Push Jira → "In Review"  (recommended)
  2) Leave Jira as-is
  [1/2, default=1]:
```

  If PM moved Jira externally (3-option conflict):

```
[jira] CONFLICT: KLC-021 Jira changed "In Review" → "Done" outside klc.
  1) Push Jira back → "In Review"  (klc wins)
  2) Keep Jira at "Done", record divergence
  3) Skip — write [!CONFLICT] to meta, show in doctor
  [1/2/3, default=3]:
```

- **Non-TTY** (CI): divergence recorded in `meta.json:jira_sync.conflicts`,
  warning on stderr. NEVER push silently.
- Limit managed mode to specific tickets: `managed_tickets: [KLC-021]`.
  Empty list (default) = all tickets.

Unresolved conflicts appear in `klc doctor` as `WARN jira-sync-conflicts`
(non-blocking by default; `--strict` to fail).

#### push() single-hop rule

`klc jira reconcile push` finds a direct Jira transition to the target status.
If no direct transition exists, it records a `transition-blocked` conflict and
shows the manual action required — it never moves klc backward.

#### pull / force-pull — Jira→klc (KLC-022)

`klc jira reconcile <KEY> pull --to <phase>` moves klc to match the current
Jira status. `--to` must be in `jira_to_klc[current_jira_status]`; direction
is auto-detected by phase index in track.

**Forward pull** (`--to` later in track): walks phase-by-phase.
- Phases with `condition=False` are auto-skipped (recorded as `event=skipped`).
- Phases with required inputs missing: **STOP** — output shows `SKIPPED
  (condition)` vs `MISSING <file>` clearly. Use `force-pull` to proceed.

**Backward pull** (`--to` earlier = rework): supersedes downstream artefacts.
Requires TTY confirmation; aborts in non-TTY (use `force-pull` + `--reason`).

**force-pull**: `klc jira reconcile <KEY> force-pull --to <phase> --reason "..."`.
`--reason` is required. Writes a `jira-force-pull` phase_history event:
```json
{"event": "jira-force-pull", "note": "<reason>", "jira_status": "...",
 "target_phase": "...", "missing_artifacts": [...], "skipped_phases": [...]}
```
These events accumulate as a retro-audit trail.

**Inline rework fork** (managed mode): when `ack/next` detects PM moved Jira
backward, the conflict prompt auto-offers pull candidates from `jira_to_klc` as
option 1, with TTY confirmation before superseding.

**Safety rule**: `jira-pull` events suppress the klc→Jira push hook — a
pull never triggers a circular push back to Jira.

`klc jira status` is **read-only** — no prompts, no state changes. Exits 1
on mismatch.

`klc jira sync` only reports + links + updates `meta.json:jira_sync`. It does
**not** change phase state; use `reconcile` for that.

#### Setup for `klc jira`

```yaml
# .klc/config/jira.yml
enabled: true
mode: mirror         # mirror | managed (KLC-021)
site:
  base_url: "https://jira.example.com"
  project_key: "KLC"
  auth_env: "JIRA_API_TOKEN"
gitlab:
  base_url: "https://gitlab.example.com/group/repo"
  blob_url: "{base_url}/-/blob/{branch}/{path}"
status_mapping:
  klc_to_jira:
    build: "In Progress"
    review: "In Review"
    archived: "Done"
  jira_to_klc:
    "In Progress": [xs-build, build]
    "In Review":   [review-lite, review]
    "Done":        [learn, archived]
artifacts:
  comment_links: true
```

#### Intake behaviour when integration is enabled

When `klc intake <KEY>` runs with integration enabled:

1. Checks whether Jira issue `<KEY>` already exists.
2. If it exists, prompts for description source:
   - **1 = klc** (default): keep local description.
   - **2 = jira**: use Jira description (stored in raw.md with markers).
   - **3 = both**: local + Jira section appended.
   - Non-interactive: `klc intake <KEY> --jira-description klc|jira|both`.
3. Adds a Jira comment with a GitLab link to `raw.md` (always, if issue exists).

#### `meta.json:jira_sync` block

Written by `klc jira sync --apply` and `klc jira reconcile push`:

```json
"jira_sync": {
  "enabled": true,
  "issue_key": "KLC-019",
  "last_synced_at": "2026-06-05T10:00:00Z",
  "last_jira_status": "In Review",
  "last_klc_phase": "review:work",
  "last_action": "push",
  "conflicts": []
}
```

`klc doctor` surfaces unresolved conflicts from this block.

---

### Legacy auto-push (`mode: mirror`, `jira-sync` command)

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
    cancelled: "Cancelled"   # terminal for `klc abort --cancel` (KLC-076)
```

`cancelled` is a terminal sentinel parallel to `archived`: a ticket closed with
`klc abort --cancel` pushes this status so its Jira issue does not linger in its
old (e.g. "In Progress") status. If your Jira workflow has no cancelled/won't-do
status, drop the key — the push then no-ops (the issue keeps its current status).

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

## Suite-green gate (KLC-049)

The full test suite must remain green across all phases.

**`klc doctor --tests`** runs `python3 -m pytest tests/ -q --ignore=tests/fixtures` and
exits 0 only when every non-skipped test passes.  Use it as a gate after each feature
branch lands:

```
klc doctor --tests
# or with a specific path for CI:
klc doctor --tests --tests-path tests/integration/
```

**Fixture-repair rule:** when a gate is added to a shared completion function
(`can_complete_discovery`, `can_complete_discovery_lite`, etc.), the implementing
agent **must** update all sibling test fixtures in the same change.  A gate that
silently breaks existing tests defeats the purpose of gating.

---

## Gate hardening (KLC-050)

Four judgment-side weaknesses hardened in KLC-050 (2026-06-25):

**Broadened no-pre-judgment lint** (`core/skills/lint_review_prompts.py`): in addition to
the canonical `do not flag X` form, `lint_text` now catches contractions and paraphrases —
`don't flag`, `ignore this issue`, `treat as minor/trivial`, `downgrade it/this/the severity`.
Benign review prose ("should not ignore edge cases") remains unflagged.

**Placeholder-aware `recorded_pick`** (`core/skills/spec_structure.py`): `recorded_pick`
returns False when the text after `Picked:` is empty, an angle-bracket placeholder
(`<approach>`, `<chosen option>`), or `TBD`/`tbd`.  Only a concrete non-empty value or a
`DECISION D-NNN` marker returns True.  Trailing whitespace does not produce a false negative.

**strict model guard** (`core/skills/model_guard.py`): `require_subagent_model(resolved)`
raises `ValueError` when `resolved` is None or has an empty model — hard rejection before
any subprocess/dispatch is invoked.  Both `runner.run_agent` and
`build_orchestrator.run_build` call it before dispatching; the soft `MODEL_NOTE` for
default-fallback sources is kept as a separate, complementary signal.

**Unified step parser** (`core/skills/phase_completion.py`): `_impl_plan_steps` now
delegates to `impl_plan_check.parse_impl_plan_steps` (single regex) and adapts its output
to the `{step: int, red_not_applicable: bool}` shape the caller at line 466 expects.  The
duplicate parser regex is gone.  The stale `core/templates/impl-plan.md.j2` and
`impl-plan-short.md.j2` (unreferenced, missing gate-required fields) were removed.

## Discovery Socratic protocol (KLC-034)

Both discovery prompts (`discovery.md` and `discovery-lite.md`) use the `AskUserQuestion`
tool for the Socratic questioning step: exactly one question per call, waiting for the answer
before asking the next. If context already answers every material unknown, the agent skips
questioning and goes straight to the approaches step.

**Live re-route signals** — two tokens emitted in `spec.md` when scope outgrows the track:

| Signal | Meaning | Advisory |
|--------|---------|---------|
| `DISCOVERY_DECOMPOSE` | Ticket spans ≥ 3 independent subsystems | Decompose before building |
| `DISCOVERY_LITE_UPGRADE_M` | S scope exceeds S ceiling | Re-route via `klc retrack <KEY> M` |

Both signals are non-blocking: `can_complete_discovery_lite` returns `(True, advisory)` when
either is present. The operator decides whether to re-route or proceed.

---

## Plan-quality gate (KLC-051)

Added in KLC-051 (2026-06-25): mechanical check at design and discovery-lite ack that catches
invented or misspelled APIs before build.

**plan-quality gate** (`core/skills/plan_quality.py::unresolved_api_refs`): extracts
`module.attr(` references from fenced code sketches in `impl-plan.md`. For every `module` that
is the basename of a real `core/skills/*.py` file, flags any `attr` not defined at the top
level of that module. Symbols introduced by the plan's own sketches (`def`/`class` inside a
fenced block) are exempt. Stdlib and third-party prefixes are ignored (low false-positive by
design). Wired into `phase_completion.can_complete_discovery_lite` (S) and `can_complete`
(design/M-L ack) immediately after the plan-completeness (KLC-036) check.

**Test-coverage discipline**: all three planning prompts (`design.md`, `discovery-lite.md`,
`test-planner.md`) now carry a mandatory rule: every AC describing a CLI, gate, or wired
behaviour maps to a test at the public entry point (not a private helper); every gate/validator
AC maps to a negative test (gate bites) plus a fail-closed test. Enforced by a prompt-regression
assert (`tests/test_prompt_regression.py::test_planning_prompts_endtoend_rule`).

**Build-ready prep: adversarial completeness-audit** — before declaring a ticket build-ready
(before `design:ack` or `discovery-lite:ack`), launch a fresh subagent to read `spec.md`,
`test-plan.md`, and `impl-plan.md` and answer:

1. Does every wired-behaviour AC have a test at the PUBLIC entry point?
2. Does every gate/validator AC have a negative test (gate bites) and a fail-closed test?
3. Do any code sketches call a `core/skills` API that does not exist (`plan_quality.unresolved_api_refs`)?
4. Is any helper defined but never wired into a real call site?

This is the planning analog of the mandatory code-reviewer required before `review-report.md`.
Findings block ack until resolved; the gate (`unresolved_api_refs`) is mechanical; the rest is
judgment confirmed by the audit.

---

## Gate-policy layer (KLC-045)

Every pick in `phases.yml` carries an explicit `gate` level that classifies how
much human judgment it needs.  The classification drives `klc ack --auto`.

### Gate levels

| Level | Meaning | Auto-proceed? |
|-------|---------|---------------|
| `auto` | Mechanical transition — no judgment needed | Always |
| `conditional` | Proceed only when all safety signals are clean | When clean |
| `decision` | Irreducibly human — spec approval, design pick, manual sign-off, merge | Never |

**Decision gates** (always pause, even with clean signals):
- `discovery-lite`: approve (spec sign-off)
- `discovery`: approve (spec sign-off)
- `design`: all three option picks + needs-rework + revise-impl-plan
- `manual`: passed / failed (manual sign-off)
- `integrate`: merged (merge is always human)

All other picks are `conditional` (approve on build, review, observe, etc.).

### `klc ack --auto`

```
klc ack <KEY> --auto
```

Applies the gate policy to the unambiguous forward pick (the pick with `goto:
"next"`, or the sole pick when there is only one).

Behaviour:
- **`auto` pick** → always proceeds.
- **`decision` pick** → always pauses; exits non-zero naming the gate.
- **`conditional` pick** → proceeds only when all seven signals are clean;
  exits non-zero listing each failing signal when any is dirty.

Plain `klc ack <KEY> [--pick N]` is unchanged — no policy is consulted.

### Seven signals (`gate_policy.collect_signals`)

| Signal | Source | Clean when |
|--------|--------|-----------|
| `advisory` | `phase_completion.can_complete` | empty string |
| `scope_expansion` | `scope_delta.compare` | no expansion, no skipped |
| `sentinels` | `scan_sentinels.scan_diff(git diff main..HEAD)` | no hits |
| `mutation` | `meta.budgets.mutation_fix_attempts` vs limit | counter below limit |
| `budget_overrun` | all budget counters vs limits | all below limit |
| `verdict` | `## Verdict` section of `review-report.md` | APPROVED / PASS, no changes-requested |
| `route_confidence` | `meta.route_confidence` | "high" or "medium" |

**Fail-closed**: any signal key absent from the signals dict is treated as dirty
(not clean).  Any source failure (no git, no `modules.json`, no
`review-report.md`) also yields a dirty value.  Only proven-clean signals allow
`conditional` to auto-proceed.

---

## Autonomous runner (`klc run`, KLC-046)

`klc run <KEY>` is a headless, single-user Python driver that walks a ticket
through the state machine on its own, reusing the KLC-045 gate-policy through the
SAME `klc ack --auto` path a human takes. It is the autonomy capstone built on
the trusted gates of phases 0–5.

```
klc run <KEY> [--cap N] [--json]
```

Each iteration reads `meta.json:phase`. At a `:work` state it dispatches the
phase agent (build via the KLC-042 orchestrator, others via `runner.run_agent`
with the resolved model), then calls `klc ack --auto` — which auto-detects
completion, walks `:work → :ack-needed`, and applies the gate policy in one call.

### Guardrails (safety-critical — the loop PAUSES, never proceeds)

The runner is bounded so it can never silently take an irreversible or risky
action. Before acting on any phase it checks, and pauses on:

| Guardrail | Fires when | Why |
|-----------|-----------|-----|
| outward-facing / irreversible | the next phase is in `_OUTWARD_PHASES = {integrate}` | integrate is the only merge/push phase — merge is always human |
| budget ceiling | any `meta.budgets` counter is at/over its limit | runaway-cost backstop |
| consecutive-auto cap | `N` consecutive auto-transitions reached (`--cap`, default 20, `KLC_AUTORUN_CAP`) | runaway-loop backstop |
| decision gate | the forward pick's gate is `decision` (applied inside `ack --auto`) | irreducibly human |
| dirty conditional gate | a `conditional` gate has a dirty signal (applied inside `ack --auto`) | fail-closed |

Every pause names which guardrail or gate fired, emits a stderr notification, and
is recorded in the per-ticket run log `.klc/tickets/<KEY>/run-log.md` (each
transition taken, plus the pause reason) so a human resuming after a pause sees
exactly what happened.

**Never merges or pushes**: `integrate` is never dispatched or acked by the
runner — it pauses at `integrate:work` and hands off to a human for the merge.

### rc / behaviour

- rc `0` — the ticket reached a terminal/clean stop (archived).
- rc `2` — the loop paused; a human must act (decision gate, dirty gate, or a
  guardrail). `ack --auto` returns rc 2 on a gate pause; any other non-zero rc
  from `ack --auto` becomes an error pause with its own message.
- rc `1` — refusal (see scope boundary below).

### Scope boundary — single-user / feature-off only

The runner runs only when the multi-user state feature is OFF
(`state_feature.enabled()` is False — the common single-user case, where
`state_tx` is a no-op and `ack --auto` behaves exactly as above). If the feature
is ON, `klc run` **refuses** (rc 1) and takes no transition: multi-user
autonomous running would need a CAS-push per ack, holder management, and rc-1
sync-error disambiguation, which are out of scope for this driver.

The consecutive-auto cap is a runaway backstop, **not** a phase budget counter:
it lives as a top-level key in the framework `config/budgets.yml` and is read by
`autorunner._cap()`, deliberately kept out of `meta.json:budgets` /
`budget._load_limits()` (which feed the `budget_overrun` gate signal).

### Relation to `/klc:run` (KLC-052)

`klc run` (this driver) and `/klc:run` (below) are different surfaces. `klc run`
is a headless Python CLI for single-user autonomy that **pauses** at every human
gate and never touches interactive phases (it hands off instead). `/klc:run` is
the prompt-driven main-loop orchestrator that runs inside Claude Code and *can*
drive interactive phases (clarify / picks) because it has an interactive channel.

---

## Orchestrator (`/klc:run`, KLC-052)

`/klc:run <KEY>` runs a ticket through its lifecycle without a human
re-reading every phase's artifacts. It is **prompt-driven main-loop
instructions** (`klc-plugin/skills/run/SKILL.md`), not a hidden Python
driver — interactive phases (clarify / human gates) can only be run
from the CC main-loop or Task-tool; `runner.py` (headless) is
forbidden from touching them.

Each iteration:
1. `klc status <KEY> --json` → `{phase_id, state, track}`.
2. `phase_resolver.resolve_phase(<KEY>, phase_id)` → the single
   phase→agent source of truth (prompt, model, `agent_type`,
   `runs_inline`, `interactive`) — derived only from `phases.yml` +
   `models.yml` + `meta.json:track`.
3. If `resolved.interactive`: **stop** — hand control to the human
   (clarify gate or an ambiguous pick).
4. Otherwise dispatch: inline for an XS fast-track phase, or
   `Task(subagent_type=resolved.agent_type, ...)` for S/M/L.
5. Parse the subagent's structured completion signal (below). On a
   clean `"done"` with no blocking questions: `klc ack --auto` +
   `klc next` (KLC-045 gate-policy throttle).

### Structured completion signal

Every `klc-<phase>` subagent ends its output with one fenced JSON
object as the last block (shared "Completion signal (orchestrator)"
block appended to every `core/agents/*.md`, regenerated into
`klc-plugin/agents/` by `plugin_gen.py`):

```json
{"phase":"design","signal":"done","artifacts":["design/options.md","impl-plan.md"],"blocking_questions":[],"next_action":"ack"}
```

`core/skills/run_signal.py` parses it (`parse_signal`) and applies the
retry policy (`should_retry`): an unparseable/mismatched signal retries
the same phase once; a second consecutive failure stops the loop.

### Mandatory intake clarify gate

`core/phases/intake.py` stamps `meta.json:clarify_required = true`
whenever `route_confidence == "low"` — unconditional on `raw.md`
content, since intake runs headless and cannot ask. The orchestrator
loop is the only place with an interactive channel, so it owns firing
the clarify pass (`core/agents/intake-triage.md`'s "Interactive
clarify" section): one `AskUserQuestion` (batch, default) or one
question at a time (serial), style from `config/clarify.yml` /
`core/skills/clarify_config.py` (fail-closed; unknown values reject
rather than silently falling back to batch). "Nothing to add" is a
valid, complete answer — mandatory means the gate always *fires*, not
that the human must produce content. Answers are written back into
`raw.md`, the route is recomputed, and the stamp is cleared before
discovery's **author** subagent (`klc-discovery`) runs on the enriched
input — no new `phases.yml` phase id, just a loop-level split between
the interactive clarify step and the background synthesis step.

The clarify style is **global only** (no per-track override) and governs
only the in-client interactive path — the headless runner (which parks
on interactive phases instead) and the manual-CLI path (a human editing
`raw.md` directly) never read it.

---

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
