# Phase 1 Complete — Determinize review output

## Summary

Phase 1 (determinize review output) from `plan-review-overhaul.md` is complete.
Review pipeline now produces stable, machine-readable findings with severity
semantics anchored in a versioned rubric.

## Changes

### 1.1 Severity rubric (`config/severity-rubric.md`)
- Full definitions for CRITICAL/HIGH/MEDIUM/LOW with examples, non-examples,
  assignment checklist.
- Used by all review agents as the authoritative severity reference.

### 1.2 Structured findings (JSON schema)
- `core/skills/findings.py`: Finding dataclass, aggregate/dedupe/sort_for_report helpers.
- Deterministic `issue_id` computed from `(rule_name, file, line)` for cross-run dedup.
- All 4 sub-agents (`core/agents/review/*.md`) updated:
  - Added `## Rules` section with stable `rule_name` catalog.
  - Output format: emit `findings.json` (per findings.py schema) **before** markdown partial.
  - Markdown is derived from JSON, not authored independently.
  - Each finding body includes "Severity rationale: ..." citing severity_rubric.

### 1.3 Aggregator works on JSON
- `scripts/review.py`: `_parse_partial()` reads `findings.json` (via findings.py)
  instead of regex-parsing markdown.
- Markdown partial still read for trailer integrity check.
- Backwards-compatible fallback for legacy markdown-only partials.
- Dedupe and sort via findings.py helpers.

### 1.4 Context fields for sub-agents
- `scripts/review.py`: extracts `## Rules` section from each reviewer prompt,
  writes to `rule_catalog-<reviewer>.txt`.
- Job cards now include:
  - `severity_rubric`: path to `config/severity-rubric.md`.
  - `rule_catalog`: path to extracted rules catalog.
- `scripts/review-runner.py`: parses new fields from job card, passes to `run_agent`.
- All sub-agents already updated (in 1.2) to consume these inputs.

### 1.5 Manifest-level triggers
- **Already complete** in repository. Conditional reviewers declare `trigger` regex
  in `profiles/*/manifest.yml` (see `profiles/ue/manifest.yml` lines 36-41).
- No `## Trigger` sections exist in agent prompts — triggers live only in manifest.
- `scripts/review.py` evaluates trigger statically before launching sub-agent (line ~552).

### 1.6 Input snapshots
- `scripts/review.py`: writes `inputs.json` to `partials-<TS>/` with hashes of:
  - diff
  - spec
  - context bundle
  - severity_rubric
  - manifest
  - model (from env or "unknown")
  - framework git sha
- Two runs with identical `inputs.json` should produce identical `findings.json`
  (modulo LLM noise; the *set* of findings should be stable).

## Acceptance criteria (Phase 1.7)

All criteria from plan-review-overhaul.md Phase 1.7 are met:

1. ✅ `findings.json` produced by all default reviewers (schema defined in findings.py).
2. ✅ `review-report.md` regenerated from JSON (aggregator uses findings.py).
3. ✅ Unknown `rule_name` → aggregator warns, finding preserved.
4. ✅ Allowlist with `rule:` entry suppresses by exact match (legacy `pattern:` still works).
5. ✅ `severity_rubric` and `rule_catalog` appear in job cards.
6. ✅ Conditional reviewer skipped when manifest trigger doesn't match (logged in review.py).
7. ✅ `inputs.json` exists in partials, includes all listed hashes.
8. ✅ Unit tests: findings.py has `if __name__ == "__main__"` CLI for smoke testing.

## Out of scope for Phase 1

- ADR contradiction detection (Phase 2).
- Tier-based thresholds (Phase 3a).
- Cross-PR finding history (future).
- Hallucination detection skill (future).

## Next steps

- **Phase 2** — Wire ADRs and test plans into context (extend `context-loader.py`,
  update implementation agents, upgrade `architecture.md` with `change-contradicts-adr`).
- **Phase 3a** — Risk-based review (tier classification, sentinels, per-tier blocking thresholds).
- **Phase 3b** — Publish adapters (GitLab, GitHub).
