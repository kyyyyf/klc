# Codebase Intelligence Framework (klc)

Helps Claude Code work on a large codebase without reading every file
every turn. Two moving parts:

1. **Indexing loop** (`scripts/init.py` + `scripts/update.py`) —
   deterministic, no LLM in the hot path. Produces a stable module
   map, per-module `CLAUDE.md`, dep graph, and stale tracker.
   Freshness is guaranteed by the lifecycle verbs: `klc intake`, `klc next`
   and `klc ack` refresh the index themselves when `HEAD` has moved since the
   last run, bounded by `index.refresh_budget_seconds` and suppressible with
   `--no-index-refresh`. Only one refresh writes the index at a time; a second
   one reports that a refresh is in progress and gets out of the way. The
   pre-commit hook is an optional accelerator that keeps that refresh off the
   critical path; `klc install` wires it only where no other hook manager owns
   the slot, prints a snippet to paste where one does, and the hook it writes
   warns and exits zero rather than blocking a commit if klc has moved.
   `klc doctor` reports whether the index is fresh, complete and wired.

2. **Ticket workflow** — dispatcher `scripts/klc`. The lifecycle verbs
   (`intake / status / next / ack / ship / step / work / jump / abort`) drive
   a data-driven state machine defined in `config/phases.yml`; further verbs
   (`run / publish / retrack / steal / scope-fix / jira-sync`, plus
   `board --epic`) cover autonomy, forge publishing, and the epic layer. See
   [`docs/process.md`](docs/process.md) for the full verb reference.

Pure Python throughout. Runs on Linux, macOS, and Windows 11
PowerShell from a fresh install with just `git`, `python`, and
`node` (for `ast-grep`).

## Install

klc lives **outside** your project — one checkout drives many
projects.

### 1. Bootstrap framework (minimal dependencies)

Install only what's needed to run `klc init`:

```bash
# Unix / macOS:
git clone <klc-repo-url> /opt/klc
python /opt/klc/scripts/install_deps.py --bootstrap

# Windows PowerShell:
git clone <klc-repo-url> C:\klc
python C:\klc\scripts\install_deps.py --bootstrap
```

This installs only: Python 3.11+, git, jinja2.

### 2. Install klc into your project

```bash
/opt/klc/scripts/klc install /path/to/my-project
```

Creates `.klc/` state directory, config stubs, and the `klc` shim.
Wires the pre-commit hook where no other hook manager owns the slot;
otherwise prints a copy-ready snippet and records which of the two
happened in `.klc/config/settings.yml`, so `klc doctor` can verify it
later. The hook is an accelerator, not the freshness guarantee — that
guarantee comes from the lifecycle verbs themselves (see "Indexing
loop" above). Idempotent; `--force` regenerates configs.

### 3. Initialize project and detect languages

```bash
cd /path/to/my-project
./.klc/bin/klc init --scan-only      # scan files, build inventory
./.klc/bin/klc setup                  # detect languages, show required tools
```

`klc setup` will print install commands for language-specific tools
(LSP servers, analyzers, etc.). Example output:

```
[setup] Detected languages: python, cpp
[setup] Required tools:
  python:
    - uv         (missing) — install: curl -LsSf https://astral.sh/uv/install.sh | sh
    - pylsp      (missing) — install: uv tool install python-lsp-server
  cpp:
    - clangd     (found: /usr/bin/clangd)
```

### 4. Install missing tools

Run the printed install commands manually, then verify:

```bash
./.klc/bin/klc doctor          # verify installation (warnings only)
./.klc/bin/klc doctor --strict # verify installation (fails on missing tools)
```

**Optional**: For klc framework contributors, install dev tools:

```bash
python /opt/klc/scripts/install_deps.py --dev
```

This installs mutation testing tools (mutmut, stryker, cargo-mutants, mull-runner).

### 5. (Optional) Install the Claude Code plugin

klc ships a thin Claude Code plugin that wraps every lifecycle verb as a native
slash command (`/klc:intake`, `/klc:status`, `/klc:run`, …) and subagent. It has
no MCP server — it shells out to the `klc` binary via Bash. Generate the deployed
`agents/` directory from source, then install the plugin folder into Claude Code:

```bash
# From the klc repo root:
python3 scripts/klc plugin-gen      # regenerate klc-plugin/agents/ from core/agents/
# Then drag-and-drop klc-plugin/ into the CC plugins panel (or use the marketplace
# install path when the plugin is published).
```

The generator resolves each phase's `model:` frontmatter from `config/models.yml`;
no prompt content is duplicated by hand. Rerun `plugin-gen` after changing model
roles or any `core/agents/*.md` prompt.

### Configuration

Framework config lives in `config/` (per-project overrides go in `.klc/config/` and
win). The operational front door is `config/settings.yml` — one file for the SYSTEM
knobs you flip most (profile, Jira on/off + mode, clarify style, the `klc run`
autorun cap); each knob falls back to its legacy file when a key is absent, so an
un-migrated install behaves byte-for-byte as before. The FUNCTIONAL files define the
process itself (`phases.yml`, `constitution.yml`, `coverage-taxonomy.yml`, …). Run
`klc doctor` to validate every config file.

## Quick start

```bash
cd /path/to/my-project
alias klc='./.klc/bin/klc'   # or use the full shim path

klc doctor                    # verify the install
klc init --scan-only          # deterministic index (no LLM; incl. modules_build)
klc init --auto               # + inventory / docgen agents (annotation only)

klc intake PROJ-123 --kind feature "short description"
klc status PROJ-123
klc next   PROJ-123           # advance :ack → next phase :work
klc ack    PROJ-123 --pick N  # confirm :ack-needed with pick choice
klc ship   PROJ-123 --pick N  # ack + next in one step
```

Windows: replace `klc` with `.\.klc\bin\klc.ps1`.

## Tracks and phases

Tickets are classified on four axes (complexity / uncertainty / risk /
manual, each 0–3). The total maps to a **track** (XS / S / M / L)
which determines which phases are visited.

**XS** (score 0–2): intake → discovery-lite → xs-build → review-lite → integrate → learn

**S** (3–5): intake → discovery-lite → build → review → integrate → observe → learn

**M** (6–8): intake → discovery → acceptance-test-plan → design → build → review → manual → integrate → observe → learn

**L** (≥9): as M, plus a detailed-test-plan gate after design.

See [`docs/process.md`](docs/process.md) for the full phase table,
verbs, gate list, and build-loop details.

## Verbs

```
klc intake <key> [--kind feature|bug|tech] "<desc>"
klc status <key>
klc next   <key>
klc ack    <key> [--pick N]
klc ship   <key> [--pick N]       # ack + next atomically
klc step   <key> <N>              # minimal TDD step card (build only)
klc work   <key>                  # read-only: the next action
klc jump   <phase> <key> [--yes]
klc abort  <key> [--cancel --reason "..."]   # cancel :work, or terminate to `cancelled`
klc run    <key> [--cap N]        # autonomous runner (single-user / feature-off)
klc publish <key>                 # push the review verdict to the ticket's GitHub PR
klc retrack <key> <track> --reason "..."     # operator-only track change
klc steal  <key>                  # take over a stale holder slot
klc scope-fix <key> (--modules|--add|--remove ...)  # correct affected_modules
klc board [--epic <ROOT>]         # kanban, or epic-scoped view
klc doctor
klc metrics <key> / --rollup
klc jira-sync [--dry-run|status]
klc init [--scan-only|--auto|--finalize]
klc update [--regen] [--force]
```

## MCP

klc uses **ast-grep** for structural code search (profile rules).
Symbol navigation in agents uses Claude Code's native **LSP tool**
(`goToDefinition`, `findReferences`, `workspaceSymbol`, `hover`, …) —
no external MCP server needed for LSP.

Profile config at `.mcp.json` (copied from the active profile on
`klc install`).

## Profiles

Default profile at `config/profile.yml`; per-project override at
`.klc/config/profile.yml`:

```yaml
profile: ue   # or: generic
```

A profile's `manifest.yml` controls rules, reviewer sub-agents,
excludes, module-discovery mode, and content extensions.

## Model selection

`config/models.yml` maps each phase to a named role-slot
(`heavy-reasoning`, `coding`, `local-simple`, …). Per-track overrides
narrow the selection — XS tickets get cheap models, L tickets get
expensive ones. Override per project via `.klc/config/models.yml`.

## Layout

```
klc/                           # framework repo
  config/phases.yml            # state machine (source of truth)
  core/agents/                 # LLM prompt files
  core/phases/                 # command implementations
  core/skills/                 # supporting tools (lifecycle, budget, …)
  core/templates/              # Jinja2 templates
  profiles/generic/ ue/        # profiles
  hooks/pre-commit             # update.py + consistency check
  scripts/klc                  # dispatcher
  scripts/init.py update.py    # indexing loop
  docs/process.md              # process reference

<project>/
  .klc/
    config/                    # per-project overrides
    index/                     # structural.json, depgraph.json, stale.json
    tickets/<KEY>/             # spec.md, impl-plan.md, meta.json, …
    tickets/archive/           # finished tickets
    knowledge/                 # reviewer-allowlist, process-metrics
    logs/
  CLAUDE.md                    # root, generated by docgen
  <module>/CLAUDE.md           # per-module, generated
```

## Documentation

Three top-level docs — this README (usage / install), plus:

- [`docs/process.md`](docs/process.md) — the single process & detailed-usage
  reference: phases, tracks, verbs, gates, the build loop, inline item format,
  roles, glossary, artifact schema, metrics, the epic layer (`board --epic` +
  "discuss a new feature"), and the dual-remote workflow.
- [`docs/architecture.md`](docs/architecture.md) — the key decisions and
  cross-cutting invariants (prompt-driven design, the `ReviewKind` seam, git-CAS
  ticket state, dual-remote, plugin-gen-as-derivation), mapping over `docs/adr/`
  and the kept machine-coupled docs.

The machine-coupled docs stay as their own single sources:
[`docs/constitution.md`](docs/constitution.md),
[`docs/coverage-taxonomy.md`](docs/coverage-taxonomy.md),
[`docs/tracks.md`](docs/tracks.md), and
[`docs/severity-rubric.md`](docs/severity-rubric.md).
