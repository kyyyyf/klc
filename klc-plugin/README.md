# klc Claude Code plugin

Thin adapter that wraps the `klc` CLI as native Claude Code slash commands
and subagents. No MCP server — the plugin shells out to the existing `klc`
binary via Bash.

## Install

```bash
# From the klc repo root, generate the agents/ directory first:
python3 scripts/klc plugin-gen

# Then install the plugin into Claude Code:
# (Drag-and-drop klc-plugin/ into the CC plugins panel, or use the
#  CC marketplace install path when the plugin is published.)
```

## Usage

After installation, Claude Code exposes slash commands for every lifecycle
verb:

| Command | What it does |
|---|---|
| `/klc:intake <KEY> <description>` | Create a ticket |
| `/klc:status <KEY>` | Show current phase and track |
| `/klc:next <KEY>` | Advance to the next phase |
| `/klc:ack <KEY> [--pick N]` | Confirm phase work is done |
| `/klc:ship <KEY>` | ack + next in one step |
| `/klc:jump <KEY> <phase>` | Jump to a specific phase |
| `/klc:abort <KEY>` | Cancel and return to previous ack |
| `/klc:step <KEY> N` | Show / advance the build step |

## Execution surface

| Phase type | Where it runs | Model |
|---|---|---|
| Heavy interactive (discovery, design, …) | CC main-loop | Set by user `/model`; guarded by MODEL_MISMATCH warning |
| Mechanical fan-out (reviewers, triage, indexing) | Subagent | Pinned in `agents/*.md` frontmatter, resolved from `models.yml` |

## MODEL_MISMATCH guard

For main-loop phases, the guard in `core/skills/model_guard.py` compares the
session model's **role rank** against the required rank for the current phase.
If they differ, it prints a symmetric warning naming roles (not concrete model
names). Equal ranks are silent.

## Regenerating agents

```bash
# After changing config/models.yml roles:
python3 scripts/klc plugin-gen
```

The generator copies `core/agents/*.md` into `klc-plugin/agents/` with the
per-phase `model:` frontmatter resolved from `models.yml`. No prompt content
is duplicated by hand.
