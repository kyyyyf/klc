# Codebase Intelligence Framework (klc)

Helps Claude (or any MCP-capable agent) work on a large codebase
without reading every file every turn. Two moving parts:

1. **Indexing loop** — `scripts/init.py` + `scripts/update.py`.
   Produces a stable module map, per-module `CLAUDE.md`, dep graph
   and the per-module symbol index.
2. **Ticket workflow** — one dispatcher `scripts/klc` with six
   verbs (`intake / status / next / ack / jump / abort`) that drive
   a data-driven state machine defined in `config/phases.yml`.
   See `docs/process-phases.md`.

Pure Python throughout — no bash, no `jq`, no `find`/`sed`/`awk`.
Runs on Linux, macOS, and Windows 11 PowerShell from a fresh install
with just `git`, `python`, `node` (for `ast-grep`).

Both halves are profile-driven. The active profile
(`config/profile.yml`, or per-project override at
`.klc/config/profile.yml`) decides which rules, reviewers, excludes,
and module-discovery mode to use. Ships with `ue` (Unreal Engine)
and `generic`.

## Install

klc lives **outside** your project — one checkout drives many
projects. Inside each project you get a tiny shim at
`.klc/bin/klc` that forwards calls to the outer klc checkout.

### Install the klc checkout (once per machine)

```bash
# Unix / macOS:
git clone <klc-repo-url> /opt/klc
python /opt/klc/scripts/install_deps.py   # checks git/python/node/ast-grep/...

# Windows PowerShell:
git clone <klc-repo-url> C:\klc
python C:\klc\scripts\install_deps.py     # auto-detects clangd in Visual Studio
```

### Bootstrap a project

From any directory:

```bash
/opt/klc/scripts/klc install /path/to/my-project
```

That creates:

- `.klc/bin/klc` — shim that exports `PROJECT_ROOT=/path/to/my-project`
  and forwards to `/opt/klc/scripts/klc`.
- `.klc/config/profile.yml` — `profile: generic` by default
  (override with `--profile ue` etc.).
- `.klc/config/ticket-id.yml` — regex for ticket keys.
- `.klc/knowledge/{reviewer-allowlist.yml, serena-deny.yml}` — seeded
  from framework templates.
- `.klc/{index,logs,reports,tickets}/` — empty.
- `.mcp.json` in the project root (copied from the active profile).
- `.gitignore` gets a klc-state block appended (no-op if already
  present).

Re-running `klc install` is idempotent; add `--force` only when you
want to regenerate configs.

## Quick start

Unix / macOS:

```bash
cd /path/to/my-project

.klc/bin/klc doctor                    # verify the install
.klc/bin/klc init                      # scans, prepares agent prompts
.klc/bin/klc init --finalize           # after the agents finish (or use --auto)

.klc/bin/klc intake PROJ-123 --kind feature "short description"
.klc/bin/klc status PROJ-123
.klc/bin/klc next   PROJ-123
.klc/bin/klc ack    PROJ-123 --pick N
```

Windows PowerShell:

```powershell
cd C:\path\to\my-project

.\.klc\bin\klc.ps1 doctor
.\.klc\bin\klc.ps1 init
.\.klc\bin\klc.ps1 init --finalize

.\.klc\bin\klc.ps1 intake PROJ-123 --kind feature "short description"
.\.klc\bin\klc.ps1 status PROJ-123
.\.klc\bin\klc.ps1 next   PROJ-123
.\.klc\bin\klc.ps1 ack    PROJ-123 --pick N
# repeat next / ack until the ticket is archived
```

Incremental refresh after pushes: `.klc/bin/klc update`.

### Updating klc itself

```bash
cd /opt/klc
git pull
```

Every project's shim picks up the new code automatically. Regenerate
the shim (`/opt/klc/scripts/klc install <project> --force`) only if
the klc repo moved or the install layout changed.

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
    agents/review/             # review sub-agents
    phases/                    # command implementations (intake.py, next.py, ack.py, jump.py, abort.py, status.py, ...)
    skills/                    # supporting tools (lifecycle, items, metrics, ...)
    rules/                     # ast-grep rules for generic languages
    templates/                 # Jinja2 templates (spec, options, impl-plan, ...)
  profiles/
    ue/                        # Unreal Engine profile
    generic/                   # default profile
  config/
    profile.yml                # active profile (project may override)
    phases.yml                 # lifecycle state machine (phases, picks, transitions)
    reviewers.yml              # review gates, mutation threshold
    reviewer-allowlist.seed.yml
    serena-deny.yml            # seed for the Serena denylist
    ticket-id.yml              # regex for ticket keys
    jira.yml                   # url_template for link-backs
  hooks/
    pre-commit                 # bash / Unix hook (delegates to python)
    pre-commit.ps1             # PowerShell sibling for Windows-only devs
  scripts/
    klc                        # the Python dispatcher
    klc-completion.bash        # bash completion
    klc-completion.ps1         # PowerShell completion
    init.py / update.py        # indexing loop
    install_deps.py            # dependency check + Windows clangd auto-detect
    review.py                  # multi-agent review orchestration
    review-runner.py           # model-dispatcher for review sub-agents
  tests/
    smoke.py                   # end-to-end acceptance test
  docs/                        # see above

<project_root>/
  .klc/                        # per-project state
    config/                    # optional overrides
    index/                     # deterministic indices regenerated by init/update
    reports/                   # review reports
    logs/                      # install/update logs
    tickets/                   # per-ticket artefacts
      <JIRA-KEY>/              # spec, design/, impl-plan, scratch/, serena-cache/,
                               # <phase>/_prompt.md cards, _superseded/ on backward jumps
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

All commands run via the shim at `.klc/bin/klc` inside the project
root. For brevity the snippets below show just `klc ...` — add the
shim prefix yourself, or add `alias klc='./.klc/bin/klc'` to your
shell.

The ticket walks a linear path through phases defined in
[`config/phases.yml`](config/phases.yml). Each phase has three states:

- `:work`        — agent or human is producing artefacts
- `:ack-needed`  — work claims to be done, awaiting confirmation
- `:ack`         — confirmed; `next` moves on

Six verbs drive the whole lifecycle:

```
klc intake <key> "<desc>"       # create the ticket (→ intake:ack-needed)
klc status <key>                # vertical path view + next-action hint
klc next   <key>                # advance :ack → next phase :work
klc ack    <key> [--pick N]     # confirm :ack-needed (picks are phase-defined)
klc jump   <phase> <key> [--yes] # cross-cut to any phase's :work (with warning)
klc abort  <key>                # cancel :work, fall back to previous :ack
```

The set of phases each ticket traverses depends on its **track**
(`XS`, `S`, `M`, `L`). `XS` tickets skip discovery / design / etc;
`L` tickets visit every phase. See `config/phases.yml`.

Typical session on an M-track feature:

```
klc intake PROJ-1 --kind feature "..."   # → intake:ack-needed
klc ack    PROJ-1 --pick 1               # → discovery:work
# run the discovery agent against .klc/tickets/PROJ-1/discovery/_prompt.md
klc ack    PROJ-1 --pick 1               # → acceptance-test-plan:work
# ... and so on until the ticket is archived.
```

When review returns CHANGES REQUESTED, `klc ack PROJ-1 --pick 2`
auto-reopens build and supersedes the old review report. When you
realise build is hopeless, `klc abort PROJ-1` returns you to the
previous `:ack` from which `klc jump design PROJ-1 --yes` starts
over.

Diagnostics anytime:

```
klc status <key>              # where is it, what's pending
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

## Model selection

`config/models.yml` maps each phase to a concrete model via named
role-slots (`heavy-reasoning`, `coding`, `local-simple`, ...). Per-
track overrides narrow the selection further — XS tickets get cheap
models, L tickets get the expensive ones. Projects override via
`.klc/config/models.yml`. Providers dispatched by
`core/skills/runner.py`: `anthropic`, `openai`, `ollama`, `google`
(deferred).

`klc init --auto` and `klc update --auto` run inventory / decompose
/ docgen / periodic agents automatically through the runner (no
paste-into-Claude-Code step). Without `--auto` the operator-driven
prompt-printing path still works.

## External reviewer (optional)

Edit `config/reviewers.yml` inside the klc checkout (e.g.
`/opt/klc/config/reviewers.yml`), set `external_reviewer.enabled: true`,
and export the API key env var named there. When the ticket reaches
`review:work`, `scripts/review.py` picks up the flag and runs the
external reviewer alongside the internal ones.
