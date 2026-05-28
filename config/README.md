# Configuration Files

This directory contains the framework-level configuration for klc. Per-project overrides can be placed in `.klc/config/` and will take precedence.

## Files

| File | Purpose | Consumer(s) | Lines |
|------|---------|-------------|-------|
| `phases.yml` | State machine definition for klc workflow phases | core/skills/phases.py, core/skills/lifecycle.py, core/skills/artefacts.py | 300 |
| `models.yml` | LLM model selection and cost tracking per phase | core/skills/models.py | 120 |
| `tiers.yml` | Risk-based tier classification (critical/core/peripheral) | core/skills/classify_tier.py | 121 |
| `sentinels.yml` | High-risk patterns that auto-escalate to CRITICAL | core/skills/scan_sentinels.py | 186 |
| `reviewers.yml` | Multi-agent code review pipeline configuration | core/skills/review.py | 54 |
| `jira.yml` | Jira integration settings (optional) | core/skills/jira_sync.py | 58 |
| `ticket-id.yml` | Ticket ID format validation pattern | core/phases/intake.py | 9 |
| `profile.yml` | Active profile selection (default: ue) | core/phases/install.py, core/phases/doctor.py, core/skills/profile-resolve.py | 10 |
| `reviewer-allowlist.seed.yml` | Seed allowlist for reviewer false-positive suppression | Copied to .klc/knowledge/ during install | 37 |

**Total**: ~865 lines

## Seed Files vs Runtime Files

- **Seed files** (e.g., `reviewer-allowlist.seed.yml`): Copied to `.klc/` during project initialization. Runtime reads from `.klc/`, not from `config/`.
- **Runtime files**: All other YAMLs are read directly by skills at runtime.

## Per-Project Overrides

Copy any file to `.klc/config/<filename>` to override the framework default for that project. For example:
- `.klc/config/profile.yml` overrides `config/profile.yml`
- `.klc/config/jira.yml` overrides `config/jira.yml`

## Validation

Run `klc doctor` to validate all config files for unknown keys and syntax errors.
