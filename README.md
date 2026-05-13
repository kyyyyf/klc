# Codebase Intelligence Framework (klc)

Helps Claude (or any MCP-capable agent) work on a large codebase
without reading every file every turn. Two moving parts:

1. **Indexing loop** — `scripts/init.sh` + `scripts/update.sh`.
   Produces a stable module map, per-module `CLAUDE.md`, dep graph
   and the per-module symbol index.
2. **Ticket workflow** — one dispatcher `scripts/klc` with
   subcommands for every phase: `intake → discover → test-plan →
   design → build → review → manual → integrate → observe → learn`.
   See `docs/process-phases.md`.

Both halves are profile-driven. The active profile
(`config/profile.yml`, or per-project override at
`.klc/config/profile.yml`) decides which rules, reviewers, excludes,
and module-discovery mode to use. Ships with `ue` (Unreal Engine)
and `generic`.

## Install

Decide where the klc repo lives **before** running anything. Two
supported layouts:

### Layout A — klc as a subdirectory of the project (simplest)

```
my-project/            ← $PROJECT_ROOT
  klc/                 ← this repo, cloned as a subdir (any name OK)
  src/
  docs/
```

Add klc as a submodule, subtree, or plain clone — any subdirectory
name works, the scripts don't hard-code `klc/`. Every command runs
from the project root:

```bash
cd my-project/
./klc/scripts/install-deps.sh
./klc/scripts/init.sh
./klc/scripts/klc intake PROJ-1 --kind feature "..."
```

`PROJECT_ROOT` defaults to the parent of the klc repo — no env var
needed.

### Layout B — one klc checkout, many projects

```
/opt/klc/              ← one clone
/work/project-a/       ← independent projects
/work/project-b/
```

Every invocation must export `PROJECT_ROOT`. An alias per project
keeps it ergonomic:

```bash
# one-off
PROJECT_ROOT=/work/project-a /opt/klc/scripts/install-deps.sh

# persistent
alias klc-a='PROJECT_ROOT=/work/project-a /opt/klc/scripts/klc'
klc-a intake PROJ-1 --kind feature "..."
```

Both layouts keep all generated state in `$PROJECT_ROOT/.klc/` —
nothing is ever written inside the klc repo itself.

## Quick start (layout A)

```bash
cd my-project/

# 1. One-time: system deps (ast-grep, jq, python, jinja2, ...)
./klc/scripts/install-deps.sh

# 2. Bootstrap the index + per-module CLAUDE.md.
./klc/scripts/init.sh                 # scans, prepares agent prompts
# run the inventory / decompose / docgen agents in Claude Code, then:
./klc/scripts/init.sh --finalize

# 3. For a new ticket:
./klc/scripts/klc intake PROJ-123 --kind feature "short description"
./klc/scripts/klc discover PROJ-123
# ... follow the prompts; dispatcher walks you through each phase
```

Incremental refresh after pushes: `./klc/scripts/update.sh`.

## Documentation

All stable docs live in `docs/`:

- [`docs/process-phases.md`](docs/process-phases.md) — the 9-phase
  model, entry points, track-aware skip rules.
- [`docs/process-roles.md`](docs/process-roles.md) — who does what
  (human / agent / script / tool) per phase.
- [`docs/process-artifacts.md`](docs/process-artifacts.md) —
  file-by-file schema for every artefact the ticket produces.
- [`docs/process-metrics.md`](docs/process-metrics.md) — metric
  catalogue and rollups.
- [`MIGRATION.md`](MIGRATION.md) — how per-project state moved into
  `.klc/`.

## Picking a profile

Default lives at `config/profile.yml`. Any project can override with
`.klc/config/profile.yml`:

```yaml
profile: ue   # or: generic, or any directory under profiles/
```

A profile's `manifest.yml` lists:

- `rules` — ast-grep rule directories.
- `sgconfig` — project-level ast-grep config (e.g. `.h → cpp`).
- `reviewers.always` / `reviewers.conditional` — review sub-agents.
- `excludes` — directories never scanned.
- `module_discovery.mode` — `build-cs` (UE) / `conventional-dirs`.
- `content_extensions` — what counts as non-code content.
- `large_project_threshold_files` — advisory size threshold.

## Layout

The klc repo is itself the framework; per-project state lives under
`$PROJECT_ROOT/.klc/` (see `MIGRATION.md`).

```
klc/                           # this repo
  core/
    agents/                    # LLM prompts (intake, discovery, test-planner, ...)
    agents/review/             # sub-agents invoked by phase 5
    phases/                    # Python phase scripts (intake.py, discover.py, ...)
    skills/                    # supporting tools (lifecycle, items, metrics, ...)
    rules/                     # ast-grep rules for generic languages
    templates/                 # Jinja2 templates (spec, options, impl-plan, ...)
  profiles/
    ue/                        # Unreal Engine profile
    generic/                   # default profile
  config/
    profile.yml                # active profile (project may override)
    reviewers.yml              # review gates, mutation threshold
    reviewer-allowlist.seed.yml
    serena-deny.yml            # seed for the Serena denylist
    ticket-id.yml              # regex for ticket keys
    jira.yml                   # url_template for link-backs
  hooks/
    pre-commit                 # opt-in consistency gate
  scripts/
    klc                        # the dispatcher
    klc-completion.bash        # bash completion
    init.sh / update.sh        # indexing loop
    install-deps.sh
    review.sh                  # invoked by `klc review`
    feature.sh / bug.sh        # deprecated wrappers (one release)
  tests/
    smoke.sh                   # end-to-end acceptance test
  docs/                        # see above

<project_root>/
  .klc/                        # per-project state
    config/                    # optional overrides
    index/                     # deterministic indices regenerated by init/update
    reports/                   # review reports
    logs/                      # install/update logs
    tickets/                   # per-ticket artefacts
      <JIRA-KEY>/              # spec, design/, impl-plan, scratch/, serena-cache/, ...
      archive/                 # finished tickets
    knowledge/                 # allowlist, serena-deny, process-metrics, few-shot
  CLAUDE.md                    # root, generated by docgen
  <modules>/<mod>/CLAUDE.md    # per-module, generated
  docs/adr/                    # ADR files (project-owned)
```

## MCP servers

| Server   | Role                                      | Used by                              |
|----------|-------------------------------------------|--------------------------------------|
| Serena   | LSP-backed symbol queries.                | Design/Build/Review on M/L tickets   |
| ast-grep | Structural AST search.                    | Inventory, discovery hints           |

Serena is gated by `core/skills/serena-call.py` — every call goes
through a track-aware policy + per-ticket cache + denylist. See
`docs/process-roles.md` for when each tool is called.

## Ticket workflow at a glance

```
klc intake <key> "<desc>"           # phase 0
klc discover <key>                  # phase 1 — writes spec.md
klc ack <key> --for discovery       # pull-ready gate
klc test-plan <key>                 # phase 2 — AC → e2e tests (S / M / L)
klc design <key>                    # phase 3 — options + ADR + impl-plan (M / L)
klc ack <key> --for design          # direction gate
klc test-plan <key> --detailed      # phase 4 — unit/integration plan (M / L)
klc build <key>                     # phase 5 — test-first loop
klc review <key>                    # phase 6 — multi-agent review
klc ack <key> --for review          # merge-approval gate
klc manual <key>                    # phase 7 — only if estimate.manual ≥ 2
klc integrate pre <key>             # phase 8 — preflight before human merge
# human merges via their team's flow
klc integrate post <key> --merge-sha <sha>
klc observe <key>                   # phase 9 — optional
klc learn <key>                     # phase 10 — retrospective + archive
```

Diagnostics anytime:

```
klc status <key>              # where is it, what's pending
klc resume <key>              # re-enter the interrupted phase
klc board                     # kanban view
klc doctor                    # install-level health check
klc metrics <key>             # per-ticket metrics JSON
klc metrics --rollup          # 30-day aggregate
```

## Conventions

- **Inline markup** for facts / assumptions / decisions — see the
  format in `docs/process-artifacts.md` and the consistency checker
  at `core/skills/consistency_check.py`.
- **Manual blocks** inside generated files are preserved verbatim:
  `<!-- BEGIN: manual --> ... <!-- END: manual -->`.
- **ADRs are not mandatory.** The design agent signals
  `ADR_NEEDED=yes|no`; the adr agent fires only on real triggers.

## External reviewer (optional)

Edit `config/reviewers.yml`, set `external_reviewer.enabled: true`,
export the API key env var named there, then:

```bash
./klc/scripts/klc review <key> --external
```
