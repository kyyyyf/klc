# Configuration Files

Framework-level configuration for klc. Per-project overrides go in `.klc/config/`
and take precedence over the framework defaults here.

The files split into two groups: **SYSTEM** (operational toggles — how the
framework runs in this install) and **FUNCTIONAL** (domain content — the process
definition itself).

## The operational front door: `settings.yml`

`settings.yml` is the one file for the SYSTEM knobs you flip most often. It is
resolved by `core/skills/settings.py`, which reads it FIRST and falls back to the
knob's legacy file when a key is absent — so an install that has not migrated
behaves byte-for-byte as before. It ships with every knob **commented out**.

Resolution ladder for each knob (project layers before framework layers, so a
project's explicit choice is never overridden by a framework-level default):

```text
.klc/config/settings.yml  ->  .klc/config/<legacy>.yml
  ->  config/settings.yml  ->  config/<legacy>.yml  ->  built-in default
```

Knobs currently fronted by `settings.yml` (each with its legacy file):

| Knob | Legacy file | Meaning |
|------|-------------|---------|
| `profile` | `profile.yml` | active profile selection |
| `jira.enabled` / `jira.mode` | `jira.yml` | Jira mirror on/off and mode |
| `clarify.style` | `clarify.yml` | clarify-gate dialogue style |
| `autorun.consecutive_auto_transitions` | `budgets.yml` | `klc run` runaway cap |

## SYSTEM files (operational — "how it runs here")

| File | Purpose | Consumer(s) |
|------|---------|-------------|
| `settings.yml` | Operational front door: profile / jira / clarify / autorun cap | core/skills/settings.py |
| `profile.yml` | Legacy active-profile selection (default: ue) | core/skills/profile-resolve.py, core/phases/{install,doctor}.py |
| `models.yml` | LLM model selection per phase / role / track | core/skills/models.py |
| `jira.yml` | Jira integration: connection, status_mapping (+ DEPRECATED legacy sync.*/url_template) | core/skills/{jira_config,jira_sync}.py, core/phases/jira.py |
| `reviewers.yml` | Multi-agent review pipeline, external reviewer, mutation gate, cascade | core/skills/review.py, core/skills/test-writer.py |
| `budgets.yml` | Per-track prompt-size limits + autorun cap | core/skills/{runner,metrics}.py, core/skills/autorunner.py |
| `clarify.yml` | Clarify-gate dialogue style (batch/serial) | core/skills/clarify_config.py |
| `ticket-id.yml` | Ticket-ID format regex | core/phases/intake.py |

## FUNCTIONAL files (domain — the process definition)

| File | Purpose | Consumer(s) |
|------|---------|-------------|
| `phases.yml` | State-machine definition of the lifecycle phases | core/skills/{phases,lifecycle,artefacts}.py |
| `tiers.yml` | Risk tiers for review (critical/core/peripheral) | core/skills/classify_tier.py |
| `sentinels.yml` | Patterns that auto-escalate a finding to CRITICAL | core/skills/scan_sentinels.py |
| `constitution.yml` | The few mandatory, machine-checkable review principles | core/skills/spec_selfcheck.py |
| `coverage-taxonomy.yml` | Requirement-coverage checklist (elicitation) | core/skills/coverage_gate.py |
| `elicitation-techniques.csv` | Catalogue of elicitation techniques (BMAD) | core/skills/elicitation.py |
| `reviewer-allowlist.seed.yml` | Seed allowlist for review false-positive suppression | seeded into .klc/knowledge/ at install |

## Seed files vs runtime files

- **Seed files** (`reviewer-allowlist.seed.yml`, and the commented `settings.yml`
  seeded by `klc install`): copied into `.klc/` at project init. Runtime reads
  from `.klc/`.
- **Runtime files**: every other YAML is read directly from `config/` (with the
  `.klc/config/` override) at runtime.

## Per-project overrides

Copy any file to `.klc/config/<filename>` to override the framework default, e.g.
`.klc/config/settings.yml` or `.klc/config/jira.yml`.

## Validation

Run `klc doctor` to validate every config file — unknown keys, syntax, and (for
`settings.yml`) key/value types.
