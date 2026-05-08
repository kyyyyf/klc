# Framework template

A clean, copy-ready snapshot of the Codebase Intelligence Framework.
No project-specific artefacts, no generated indexes, no absolute paths.

## What's inside

```
framework/
  core/        # engine-agnostic agents, skills, rules, templates
  profiles/
    ue/       # Unreal Engine profile
    generic/  # default profile (src/lib/pkg conventions)
  config/
    profile.yml      # which profile is active
    reviewers.yml    # review gates, external reviewer, mutation thresholds
  scripts/     # init / update / feature / bug / review / install-deps
  index/       # .gitkeep only; runtime output lands here
  logs/        # .gitkeep only; runtime output lands here
  reports/     # .gitkeep only; runtime output lands here
  README.md    # how the framework works
```

## Installing into a new project

From your project root:

```bash
cp -r /path/to/this/template/framework .
cp framework/profiles/ue/mcp.json .mcp.json      # or profiles/generic/mcp.json
./framework/scripts/install-deps.sh              # checks Serena, ast-grep, etc.
./framework/scripts/init.sh                      # scans the repo
# Follow the prompts init.sh prints:
#   inventory -> decompose -> docgen
./framework/scripts/init.sh --finalize           # record the baseline sha
```

## Switching profiles

Edit `framework/config/profile.yml`:

```yaml
profile: ue        # or: generic, or any directory under framework/profiles/
```

The active profile decides which ast-grep rules, which review
sub-agents, which exclusion patterns, and which module-discovery mode
the skills use. See `framework/README.md` for the full manifest schema.

## Adding your own profile

Create `framework/profiles/<your-name>/` with:

- `manifest.yml` — lists rules, reviewers, excludes, module-discovery
  mode, content extensions, optional hooks.
- `mcp.json` — Serena + ast-grep config to drop into `.mcp.json`.
- Optional: `sgconfig.yml`, custom `rules/<lang>/`, custom reviewers
  under `agents/review/`, hooks under `hooks/`.

Point `framework/config/profile.yml` at your profile and run
`./framework/scripts/init.sh`.

## Regenerating this template

If you change the live `framework/` and want to refresh this template,
from the repo root:

```bash
rsync -a --delete \
  --exclude='index/*' --exclude='logs/*' --exclude='reports/*' \
  --exclude='.last-run' --exclude='__pycache__' --exclude='*.pyc' \
  framework/ template/framework/
for d in index logs reports; do : > template/framework/$d/.gitkeep; done
```
