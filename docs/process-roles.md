# Role map — who does what across the phases

One row per phase. "Human" / "Agent" / "Entry" / "Tool" columns show
who is responsible; links point to the file that implements the role.

Legend:
- **Human** — a decision only a person can make (intent, direction,
  merge approval, manual sign-off).
- **Agent** — LLM prompt at `core/agents/*.md` executed by Claude Code
  (or any MCP-capable client). Agent work runs against the
  `_prompt.md` card written into `.klc/tickets/<key>/<phase>/` when
  the phase enters `:work`.
- **Entry** — how the phase is entered and exited. All entries use
  the six verbs (`intake` / `status` / `next` / `ack` / `jump` /
  `abort`); the state machine that routes them lives in
  [`config/phases.yml`](../config/phases.yml).
- **Tool** — MCP server or CLI tool the script/agent uses: Serena,
  ast-grep, git, external reviewer LLMs.

All dispatch goes through `scripts/klc`; there are no phase-specific
subcommands any more. The table below names **phase ids**, not
commands — the user always types `klc next` / `klc ack --pick N`
regardless of which phase they're about to enter.

| # | Phase id | Human | Agent | Entry (from `:ack`) · Exit (at `:ack-needed`) | Tool |
|---|----------|-------|-------|-----------------------------------------------|------|
| — | init (one-off) | — | `core/agents/inventory.md` + `core/agents/decompose.md` + `core/agents/docgen.md` | `klc init` · — | ast-grep, git |
| — | update (cron)  | — | `core/agents/periodic.md` | `klc update` · — | ast-grep, git, `serena-call` on L only |
| 0 | `intake`               | types the raw description | `core/agents/intake.md`        | `klc intake <key> "<desc>"` · `klc ack <key> --pick 1` | git (reads user config) |
| 1 | `discovery`            | acks pull-ready + track   | `core/agents/discovery.md` (wraps `core/agents/validator.md`) | `klc next` · `klc ack --pick 1|2` | ast-grep; Serena only on L with override |
| 2 | `acceptance-test-plan` | — | `core/agents/test-planner.md` (acceptance mode) | `klc next` · `klc ack --pick 1|2` | — |
| 3 | `design`               | acks direction + ADR    | `core/agents/design.md` + `core/agents/adr.md` + `core/agents/plan.md` | `klc next` · `klc ack --pick 1..4` (1/2/3 = option A/B/C, 4 = rework) | Serena (verify symbols on M/L via `serena-call.py`) |
| 4 | `detailed-test-plan`   | — | `core/agents/test-planner.md` (detailed mode) | `klc next` · `klc ack --pick 1|2` | — |
| 5 | `build`                | watches on escalation signals | `core/agents/test.md` + `core/agents/impl.md` + `core/agents/validator.md` | `klc next` · `klc ack --pick 1` | Serena, ast-grep, test runners, mutation tools |
| 6 | `review`               | acks merge approval     | `core/agents/review.md` + `core/agents/review/*.md` (driven by `scripts/review.py`) | `klc next` · `klc ack --pick 1` (approve) · `klc ack --pick 2` (request-changes, auto-jumps to `build:work`, supersedes review) | Serena, external reviewer LLM (optional) |
| 7 | `manual`               | ticks the checklist     | `core/agents/manual-check.md` | `klc next` · `klc ack --pick 1` (passed) · `klc ack --pick 2` (failed, auto-jumps to `build:work`, supersedes review + manual) | — |
| 8 | `integrate`            | runs `git merge` between ticks | built-in checklist (no agent prompt) · `core/agents/consistency.md` on tick 1 | `klc next` · `klc ack --pick 1` (once both ticks done) | git, `items.py validate`, `consistency_check.py` |
| 9 | `observe`              | decides when observation window closes | — (no agent; `_prompt.md` is a monitoring checklist) | `klc next` · `klc ack --pick 1` (clean) · `--pick 2` (regression → `build:work`) · `--pick 3` (rollback → `learn:work`) | — |
| 10 | `learn`               | reviews proposed allowlist / few-shot edits | `core/agents/retrospective.md` | `klc next` · `klc ack --pick 1` (archive) · `--pick 2` (extract-to-CLAUDE.md then loop) | `metrics.py rollup`, `serena_deny.py propose` |

## Operational commands (not phases)

| Command | Script | Purpose |
|---------|--------|---------|
| `klc status <key>` | `core/phases/status.py` | Vertical path view of the ticket's current position. Read-only. |
| `klc board`        | `core/phases/board.py`  | Kanban view of every live ticket. |
| `klc doctor`       | `core/phases/doctor.py` | Install-level health check. Safe on CI. |
| `klc metrics <key>` / `klc metrics --rollup` | `core/skills/metrics.py` | Per-ticket JSON or 30-day rollup. |
| `klc reindex <key>` | `core/skills/items.py index` | Rebuild `.index.json` of inline items. |
| `klc install <project>` | `core/phases/install.py` | Bootstrap a project to use this klc checkout. |
| `klc init` / `klc update` | `scripts/init.py` / `scripts/update.py` | Indexing loop. |

## Tools used across phases

- **Serena** (LSP-backed symbol queries). Gated by `core/skills/serena-call.py`; track-aware policy blocks XS from all phases, S outside Build, etc. Cache per-ticket at `.klc/tickets/<key>/serena-cache/`.
- **ast-grep** — structural code search (profile rules at `profiles/<name>/rules/`). Available everywhere, no gate.
- **git** — every phase that touches files expects a clean-enough working tree. `klc doctor` surfaces `git status` warnings.
- **Test runners / mutation tools** — detected when entering `acceptance-test-plan:work` and recorded in `.klc/index/test-framework.json`. Not framework-shipped; install per project.

## Data stores and command I/O

Four diagrams. The first is a high-level summary: who writes to
each data store and who reads it, at the level of command groups.
The next three drill into the heavy-context phases — Discovery,
Design, Build — where the I/O decisions directly drive how much
context each agent consumes.

**Conventions (shared across all four diagrams):**

- Rounded nodes (`([...])`) are durable data stores.
- Rectangles are commands (phase scripts from `core/phases/`, plus
  the two indexing-loop scripts `init.py` / `update.py`).
- Solid arrows are reads, dashed arrows are writes.
- Labels on arrows mark conditional flow (track-specific, or only
  on certain inputs).

### Diagram 1 — Overview: who writes / who reads

Per-store summary at the group level. Discovery, Design, Build,
Review and Learn are shown as monolithic blocks — detail lives in
the next three diagrams and in the overall phase map. The point of
this one is to see the **asymmetry**: Learn is almost the only
writer of knowledge; indexing is almost the only writer of indices;
every phase script reads its predecessors' artefacts.

```mermaid
flowchart LR
    %% stores
    code(["Source code"])
    projdocs(["Project docs<br/>(docs/adr, README, wiki)"])
    index(["Indices<br/>.klc/index/"])
    tickets(["Ticket artefacts<br/>.klc/tickets/&lt;KEY&gt;/"])
    knowledge(["Knowledge base<br/>.klc/knowledge/"])
    scratch(["Scratchpad"])
    serena(["Serena LSP + cache"])
    reviews(["Review artefacts<br/>.klc/reports/"])
    logs(["Logs &amp; metrics"])

    %% command groups
    idxloop[Indexing loop<br/>init / update]
    intake[Intake]
    discovery[Discovery]
    design[Design]
    testplan[Test planning]
    build[Build]
    review[Review]
    manualmerge[Manual +<br/>Integrate +<br/>Observe]
    learn[Learn]

    %% indexing
    code --> idxloop
    projdocs --> idxloop
    idxloop -.-> index

    %% tickets — who writes
    intake -.-> tickets
    discovery -.-> tickets
    design -.-> tickets
    testplan -.-> tickets
    build -.-> tickets
    manualmerge -.-> tickets
    learn -.-> tickets

    %% tickets — who reads
    tickets --> discovery
    tickets --> design
    tickets --> testplan
    tickets --> build
    tickets --> review
    tickets --> manualmerge
    tickets --> learn

    %% code / docs as read inputs
    code --> discovery
    code --> build
    code --> review
    projdocs --> discovery
    projdocs --> design

    %% index used by design-time phases
    index --> discovery
    index --> design
    index --> testplan
    index --> build

    %% serena only on M/L ticket-time phases
    design <-.M/L only.-> serena
    build <-.-> serena
    review <-.verify.-> serena

    %% scratch lives with ticket phases that need long traces
    build <-.-> scratch
    review -.overflow.-> scratch
    scratch --> manualmerge

    %% reviews
    review -.-> reviews
    reviews --> learn

    %% knowledge asymmetry
    knowledge --> discovery
    knowledge --> review
    knowledge --> learn
    learn -.-> knowledge
    intake -.append.-> knowledge

    %% logs — write by many, read by Learn
    discovery -.-> logs
    design -.-> logs
    build -.-> logs
    review -.-> logs
    serena -.-> logs
    logs --> learn

    classDef store fill:#fef3c7,stroke:#a16207,stroke-width:1px;
    classDef cmd   fill:#e0f2fe,stroke:#075985,stroke-width:1px;
    class code,projdocs,index,tickets,knowledge,scratch,serena,reviews,logs store;
    class idxloop,intake,discovery,design,testplan,build,review,manualmerge,learn cmd;
```

Key observations:

- **Knowledge** has one regular writer (Learn) plus a single
  append-only touch from Intake. Every other phase only reads it.
- **Indices** are written by the indexing loop and read by every
  design-time phase. No ticket script writes them.
- **Serena** is gated: always dashed + conditional. XS tickets
  don't talk to it at all.
- **Logs** are fan-in from most phases, fan-out to Learn only.

### Diagram 2 — Discovery

Discovery is the widest fan-in of the ticket flow and the second-
biggest LLM spend after Build. The agent is deliberately kept off
Serena on M / L (track-policy in `core/skills/serena-call.py`); it
leans on the materialized indices instead.

```mermaid
flowchart LR
    %% stores (ticket artefacts grouped)
    code(["Source code"])
    projdocs(["Project docs<br/>docs/adr, external wiki"])
    rootclaude(["Root &amp; module<br/>CLAUDE.md"])
    modules(["index/modules.json"])
    sbm(["index/symbols_by_module.json"])
    structural(["index/structural.json"])
    raw(["ticket/raw.md"])
    meta(["ticket/meta.json"])
    spec(["ticket/spec.md"])
    tindex(["ticket/.index.json"])
    related(["knowledge/<br/>tickets-index.jsonl"])
    rolldex(["knowledge/<br/>process-metrics.json"])
    deny(["knowledge/serena-deny.yml"])
    tokenlog(["logs/tokens.jsonl"])
    serena(["Serena LSP +<br/>per-ticket cache"])
    scratch(["ticket/scratch/"])

    %% command
    discovery[discovery:work<br/>core/agents/discovery.md]

    %% reads
    raw --> discovery
    meta --> discovery
    modules --> discovery
    sbm --> discovery
    structural --> discovery
    rootclaude --> discovery
    projdocs --> discovery
    related --> discovery
    rolldex --> discovery
    deny --> discovery

    %% optional deeper reads — only when a QUESTION points back to code
    code -.on-demand.-> discovery

    %% Serena — disabled by default on M/L by policy; override via
    %% .klc/config/serena-policy.yml
    serena <-.project<br/>override only.-> discovery

    %% scratch — opened when related-ticket chase or cross-ticket
    %% reasoning gets long
    scratch <-.long traces.-> discovery

    %% writes
    discovery -.-> spec
    discovery -.track, estimate,<br/>affected_modules.-> meta
    discovery -.-> tindex
    discovery -.-> tokenlog
    discovery -.append entry.-> related

    classDef store fill:#fef3c7,stroke:#a16207,stroke-width:1px;
    classDef cmd   fill:#e0f2fe,stroke:#075985,stroke-width:1px;
    class code,projdocs,rootclaude,modules,sbm,structural,raw,meta,spec,tindex,related,rolldex,deny,tokenlog,serena,scratch store;
    class discovery cmd;
```

Why so many read arrows: Discovery is the only phase that has to
bridge between raw human text (`raw.md`), project structure
(indices + CLAUDE.md), institutional memory (knowledge base) and —
rarely — code. Without the indices this fan-in would be direct from
source, which is what the overall design prevents.

### Diagram 3 — Design

Design's I/O is narrower but deeper. It reads the acceptance
test plan written in phase 2 to make sure the option choice
respects it. Serena access is the first heavy use: symbol
verification is mandatory for every symbol mentioned in options /
ADR on M/L tickets.

```mermaid
flowchart LR
    %% stores
    spec(["ticket/spec.md"])
    tplan(["ticket/test-plan.md<br/>(acceptance section)"])
    meta(["ticket/meta.json"])
    options(["ticket/design/options.md"])
    adr(["ticket/design/adr.md"])
    implplan(["ticket/impl-plan.md"])
    tindex(["ticket/.index.json"])
    rootclaude(["Root &amp; module<br/>CLAUDE.md"])
    modules(["index/modules.json"])
    sbm(["index/symbols_by_module.json"])
    adrhist(["docs/adr/<br/>project-owned"])
    deny(["knowledge/serena-deny.yml"])
    tokenlog(["logs/tokens.jsonl"])
    serenacalls(["ticket/serena-calls.log"])
    serena(["Serena LSP +<br/>per-ticket cache"])
    scratch(["ticket/scratch/"])

    %% command
    design[design:work<br/>core/agents/design.md<br/>+ adr.md + plan.md]

    %% reads
    spec --> design
    tplan --> design
    meta --> design
    rootclaude --> design
    modules --> design
    sbm --> design
    adrhist --> design
    deny --> design

    %% serena mandatory on M/L for any symbol cited in options
    serena <-.M/L:<br/>verify symbols.-> design

    %% scratch for options comparison / decision trace
    scratch <-.-> design

    %% writes
    design -.-> options
    design -.ADR_NEEDED=yes.-> adr
    design -.-> implplan
    design -.adr_triggered.-> meta
    design -.-> tindex
    design -.-> tokenlog
    design -.serena-call save.-> serenacalls

    classDef store fill:#fef3c7,stroke:#a16207,stroke-width:1px;
    classDef cmd   fill:#e0f2fe,stroke:#075985,stroke-width:1px;
    class spec,tplan,meta,options,adr,implplan,tindex,rootclaude,modules,sbm,adrhist,deny,tokenlog,serenacalls,serena,scratch store;
    class design cmd;
```

Three edges worth noting:

- `tplan → design` is what makes TDD real: the option evaluation
  knows which acceptance tests must stay easy to write.
- `adrhist → design` brings prior project-wide decisions into the
  options context; it's why design starts inside known constraints.
- Every arrow into `serena` is gated by `serena-call.py` — the
  denylist (`deny` node) and per-ticket cache filter each query.

### Diagram 4 — Build

Build is where everything meets: code changes, test writes, Serena
reads to avoid hallucinating signatures, scratch for long iteration
traces, budget counters to bound the loop. Most store edges here
are bidirectional because the TDD loop reads, writes, re-reads.

```mermaid
flowchart LR
    %% stores
    spec(["ticket/spec.md"])
    tplan(["ticket/test-plan.md<br/>(both sections)"])
    implplan(["ticket/impl-plan.md"])
    meta(["ticket/meta.json"])
    tindex(["ticket/.index.json"])
    code(["Source code"])
    tests(["Test files under<br/>modules' test/ dirs"])
    modules(["index/modules.json"])
    sbm(["index/symbols_by_module.json"])
    testfw(["index/test-framework.json"])
    phash(["index/per-module-hash.json"])
    budgets(["ticket/meta.json:<br/>budgets counter"])
    tokenlog(["logs/tokens.jsonl"])
    serenacalls(["ticket/serena-calls.log"])
    serena(["Serena LSP +<br/>per-ticket cache"])
    scratch(["ticket/scratch/"])

    %% commands inside Build (test-first loop)
    build[build:work]
    testw[test-writer.py<br/>core/agents/test.md]
    implw[impl agent<br/>core/agents/impl.md]
    verify[verifier<br/>core/agents/validator.md]

    build --> testw
    build --> implw
    build --> verify

    %% read heavy from ticket + indices + code
    spec --> testw
    tplan --> testw
    sbm --> testw
    testfw --> testw
    tests --> testw
    code --> testw

    spec --> implw
    implplan --> implw
    sbm --> implw
    modules --> implw
    code --> implw
    phash --> implw

    tests --> verify
    code --> verify

    %% Serena — unfettered on M/L, Build-only on S, denied on XS.
    serena <-.S/M/L.-> testw
    serena <-.S/M/L.-> implw
    serena <-.S/M/L.-> verify

    %% writes — code / tests land on disk, plan is updated when
    %% reality diverges, scratch holds intermediate state, logs
    %% grow on every iteration.
    testw -.-> tests
    implw -.-> code
    implw -.DECISION items<br/>on divergence.-> implplan
    verify -.iterations,<br/>mutation_score.-> meta
    verify -.red-fix,<br/>mutation-fix counters.-> budgets

    testw -.-> scratch
    implw -.-> scratch
    scratch --> testw
    scratch --> implw

    testw -.-> tokenlog
    implw -.-> tokenlog
    verify -.-> tokenlog
    testw -.serena-call save.-> serenacalls
    implw -.serena-call save.-> serenacalls

    build -.-> tindex
    build -.build_head_sha<br/>on exit.-> meta

    classDef store fill:#fef3c7,stroke:#a16207,stroke-width:1px;
    classDef cmd   fill:#e0f2fe,stroke:#075985,stroke-width:1px;
    class spec,tplan,implplan,meta,tindex,code,tests,modules,sbm,testfw,phash,budgets,tokenlog,serenacalls,serena,scratch store;
    class build,testw,implw,verify cmd;
```

Four things to read off this diagram:

- **Tests and code are the only durable outputs** — everything else
  is meta. The whole diagram exists to make that one arrow
  (`implw -.-> code`) trustworthy.
- **Bidirectional with `scratch`**: the test and impl agents dump
  intermediate reasoning (failing stack traces, candidate fixes) to
  the scratchpad and re-read it on the next iteration. Without it
  the TDD loop either pollutes `impl-plan.md` or re-does the same
  reasoning.
- **`per-module-hash.json` is the drift alarm**: if an impl step
  changes a module's public API, the hash changes, periodic flags
  it, and the next Discovery on a related ticket knows the
  surroundings shifted.
- **Budget counters live in `meta.json`** (shown as a separate node
  for clarity). The verifier bumps them; when a counter trips its
  limit the phase script writes `meta.json:blocked_reason` and
  stops — the human takes over.

### Commands absent from these diagrams by design

- **Operational commands** (`klc status`, `klc board`, `klc doctor`,
  `klc ack`, `klc jump`, `klc abort`, `klc reindex`). They read
  `ticket/meta.json` and `knowledge/tickets-index.jsonl` only;
  drawing them on top of diagrams 2–4 would clutter the I/O story
  without new architectural signal.
- **Review sub-agents** (security, architecture, performance,
  test-coverage, + profile-specific ones for UE etc.). They share
  the same inputs/outputs as the `review` phase; they sit behind
  that one node on diagram 1. Per-sub-agent I/O is not
  architectural — each one reads the same bundle and writes a
  partial.
- **Test planning, Manual, Integrate, Observe, Learn**. Their I/O
  is either obvious from the artefact naming (manual,
  retrospective) or already implied by diagram 1. If a later
  agent-context review shows one of them grew expensive, it earns
  its own diagram.

## Human-gate summary

The obligatory gates (always present) are three `:ack-needed`
states:

1. `discovery:ack-needed` — pull-ready. `klc ack <key> --pick 1|2`.
2. `design:ack-needed` — direction + option choice. `klc ack <key> --pick 1..4`.
3. `review:ack-needed` — merge approval. `klc ack <key> --pick 1|2`.

Conditional gates (only when the track includes the phase):

- `manual:ack-needed` (M, L only) — `klc ack <key> --pick 1|2`.
- `observe:ack-needed` (S, M, L) — `klc ack <key> --pick 1|2|3`.
- `learn:ack-needed` (every track) — `klc ack <key> --pick 1|2`.

Everything else is LLM-driven. Agents escalate to human on the
signals enumerated in `process-phases.md`, not on a schedule.
