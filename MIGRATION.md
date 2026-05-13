# Migration notes

Two layout changes have happened since the original nested-framework
shape. This document covers both so upgraders can skip straight to
the relevant step.

- **Migration 1** — per-project state moved out of the framework
  tree into `$PROJECT_ROOT/.klc/`.
- **Migration 2** — the framework repo flattened: what used to be
  `framework/core/...` is now just `core/...` at the repo root.

New installs need neither migration. `init.sh` already creates the
right layout.

## Migration 1: per-project state → `.klc/`

All indices, reports, logs, tickets, and caches live under
`$PROJECT_ROOT/.klc/`. The klc repo itself never writes inside its
own tree.

### What moved where

| Old path                                     | New path                                      |
|----------------------------------------------|-----------------------------------------------|
| `framework/index/*.json`                     | `.klc/index/*.json`                           |
| `framework/.last-run`                        | `.klc/index/.last-run`                        |
| `framework/logs/*.log`                       | `.klc/logs/*.log`                             |
| `framework/reports/review-*.md`              | `.klc/reports/review-*.md`                    |
| `framework/reports/pending-*/`               | `.klc/reports/pending-*/`                     |
| `framework/reports/partials-*/`              | `.klc/reports/partials-*/`                    |
| `framework/index/pending-bug.md`             | `.klc/index/pending-bug.md`                   |
| `framework/index/pending-feature.md`         | `.klc/index/pending-feature.md`               |
| *(new)* accumulated knowledge                | `.klc/knowledge/`                             |
| *(new)* per-ticket artefacts + scratchpads   | `.klc/tickets/<KEY>/…`                        |

Unchanged:

- `config/*` — framework-wide defaults (`profile.yml`, `reviewers.yml`,
  `reviewer-allowlist.seed.yml`).
- `profiles/*` — manifests, rules, hooks.
- `core/*` — agents, skills, templates.
- `CLAUDE.md` at project root and per-module — stays with the code.
- `docs/adr/` — project-owned.

### One-shot migration (from the project root)

```bash
mkdir -p .klc/index .klc/reports .klc/logs .klc/knowledge

# Indices, logs, reports, last-run baseline. Paths below assume the
# old layout where the framework was cloned into `framework/`. If you
# used a different name, adjust.
[ -d framework/index   ] && mv framework/index/*   .klc/index/   2>/dev/null || true
[ -f framework/.last-run ] && mv framework/.last-run .klc/index/.last-run
[ -d framework/logs    ] && mv framework/logs/*    .klc/logs/    2>/dev/null || true
[ -d framework/reports ] && mv framework/reports/* .klc/reports/ 2>/dev/null || true

# Seed the per-project allowlist (optional — review.sh falls back to
# config/reviewer-allowlist.seed.yml when the project copy is missing).
[ -f framework/config/reviewer-allowlist.yml ] \
  && cp framework/config/reviewer-allowlist.yml .klc/knowledge/
```

Update `.gitignore` in the project root:

```gitignore
# klc state — keep history of decisions, drop regenerable indices.
.klc/index/
.klc/logs/
.klc/reports/partials-*
.klc/reports/pending-*
!.klc/reports/review-*.md
# Keep team knowledge and ticket artefacts in git.
!.klc/tickets/
!.klc/knowledge/
```

## Migration 2: flat repo (no more inner `framework/`)

The framework repo used to have an extra `framework/` directory
inside the clone — scripts lived at `<clone>/framework/scripts/klc`,
config at `<clone>/framework/config/`, etc. That inner directory is
gone. Scripts now live at `<clone>/scripts/klc`, config at
`<clone>/config/`, and so on.

### Impact on existing checkouts

Anyone who cloned the framework before this migration needs either a
fresh clone or a `git pull` of the commit that flattens the tree.
`scripts/klc`, `core/`, `config/` will move up one level inside the
clone; nothing inside `.klc/` changes.

### Impact on invocation paths

| Old invocation                                    | New invocation                        |
|---------------------------------------------------|---------------------------------------|
| `./framework/scripts/klc ...`                     | `./klc/scripts/klc ...` (layout A)    |
| `PROJECT_ROOT=... /opt/klc-framework/scripts/klc` | `PROJECT_ROOT=... /opt/klc/scripts/klc` |
| `./framework/scripts/init.sh`                     | `./klc/scripts/init.sh`               |
| `./framework/scripts/review.sh ...`               | `./klc/scripts/review.sh ...`         |
| Symlink `framework/hooks/pre-commit`              | Symlink `<klc-clone>/hooks/pre-commit` |

Any CI / runbooks that hard-coded `framework/` need a one-line find
and replace.

### Name of the subdirectory

In layout A (klc as a subdir of the project) the directory name is
**arbitrary** — `klc/`, `klc-fw/`, `framework/`, `.klc-src/`. Scripts
resolve their own root from `$(dirname "${BASH_SOURCE[0]}")/..`,
they don't look for a specific directory name. The README uses
`klc/` as the running example.

## Multi-project setup (layout B)

When one klc clone drives several projects, keep it outside any
project tree:

```bash
git clone <klc-repo> /opt/klc

PROJECT_ROOT=/work/project-a /opt/klc/scripts/init.sh
PROJECT_ROOT=/work/project-b /opt/klc/scripts/init.sh
```

Each project gets its own `.klc/`. Pick the active profile per
project in `.klc/config/profile.yml` (takes precedence over
`config/profile.yml`).

## Verification

Run the smoke test from the klc repo root:

```bash
bash tests/smoke.sh
```

It provisions a throw-away project, exercises `file-scanner →
dep-graph → public-api-filter → module-writer`, runs every skill's
round-trip (scratch, serena-call, items_verify, per_module_hash,
serena_deny), and drives one synthetic ticket through phases 0–9
including the integrate-pre/post bookends.

## Troubleshooting

- **`profile-resolve: no profile.yml with a profile: key found`** —
  you removed `config/profile.yml` from the klc repo without seeding
  a per-project one. Either restore it or add
  `.klc/config/profile.yml` with `profile: generic`.
- **Scripts still write to `framework/index/`** — you're running a
  pre-Migration-1 copy. `grep -r 'framework/index'` across the klc
  repo should match nothing but docs referencing the old path in
  this file.
- **`.klc/` appears in `file-scanner` output** — the baseline
  excludes list was customised. Add `\.klc` to the baseline regex in
  `core/skills/file-scanner.sh` / `core/skills/dep-graph.sh` (the
  shipped versions already exclude it).
- **Pre-commit hook says "klc repo not found"** — either clone klc
  as a subdirectory of the project (any name works), or export
  `KLC_FRAMEWORK_ROOT=/path/to/klc` before committing.
