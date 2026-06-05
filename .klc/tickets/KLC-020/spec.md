---
ticket: KLC-020
kind: feature
authority: human
last_generated: 2026-06-05
risk_tags: []
---

# KLC-020 — Jira integration MVP: read-only core + enrich

## Goals

Build the side-effect-free foundation of the `klc jira` namespace: config,
fakeable REST client, GitLab artefact links, `klc jira status` (read-only),
and intake duplicate-check. No state changes to klc or Jira phases — that
is KLC-021/022. This is part 1 of 3.

## Problem / Context

Today `core/skills/jira_sync.py` does one-way push (phase→status) via a
hook at `lifecycle.py:137` ([!FACT src=core/skills/lifecycle.py:137]). There
is no `klc jira` command namespace, no GitLab artefact links, no
duplicate-check on intake. This ticket lays the read-only groundwork so
KLC-021 (push/managed) and KLC-022 (pull) build on a tested base.

[!DECISION D-001] klc-key == Jira-key always (single project) — no key mapping.
[!DECISION D-002] All artefacts klc-owned; Jira stores only GitLab links. AC
are not special — same as any lifecycle artefact.
[!DECISION D-003] `klc jira status` is READ-ONLY: no network state change, no
prompts. Divergence forks happen only at ack/next (KLC-021).

## Acceptance Criteria

1. AC-1: `config/jira.yml` extended with: `site.project_key`,
   `gitlab.base_url` + `gitlab.blob_url` template (`{base_url}/-/blob/{branch}/{path}`),
   `status_mapping.klc_to_jira` + `status_mapping.jira_to_klc` (candidate lists),
   `artifacts.paths`, `mode: mirror|managed`. `validate_config.py` schema updated;
   `klc doctor` passes.
2. AC-2: `core/skills/jira_config.py` (new) loads + validates jira.yml:
   rejects missing `base_url`/`auth_env`, missing either mapping, and
   malformed gitlab templates. Returns a typed config object.
3. AC-3: `core/skills/jira_client.py` (new) — thin REST client with methods
   `get_issue(key)`, `get_transitions(key)`, `transition_issue(key, id, fields=None)`,
   `add_comment(key, body)`, `get_current_user()`. Client is injectable/fakeable
   so tests run with zero network.
4. AC-4: `core/skills/jira_artifacts.py` (new) — builds GitLab blob links for
   artefacts that EXIST on disk (per `artifacts.paths`). Returns a comment-ready
   markdown link table. Does NOT upload files. Missing files omitted.
5. AC-5: `core/phases/jira.py` (new) + `scripts/klc` registers `jira` subcommand.
   `klc jira status <KEY>` prints klc phase, Jira status, and MISMATCH line if
   they differ per `klc_to_jira`. Read-only, no prompts, no transitions.
6. AC-6: intake dup-check — when integration enabled and `klc intake <KEY>` runs:
   GET issue by key; if exists → inline warning + description-source choice
   (1=klc, 2=jira, 3=both), with `--jira-description klc|jira|both` for
   non-interactive. Jira description stored in raw.md between markers
   `<!-- klc:jira-description KEY -->` … `<!-- /klc:jira-description -->`.
7. AC-7: every intake with integration enabled adds a Jira comment linking to
   raw.md (GitLab blob URL). Comment carries "moved by klc" provenance line.
8. AC-8: artefact-link comments are IDEMPOTENT — re-running updates the existing
   marker-tagged comment, never duplicates.

## Non-goals

- Push/pull state changes (KLC-021/022).
- Managed-mode interactive hook (KLC-021).
- AC sync, create_missing_issue, multi-hop transitions (deferred).

## Affected modules

- `config/jira.yml` — schema extension
- `core/skills/jira_config.py` (new)
- `core/skills/jira_client.py` (new)
- `core/skills/jira_artifacts.py` (new)
- `core/phases/jira.py` (new)
- `core/phases/intake.py` — dup-check + description source
- `core/skills/validate_config.py` — jira.yml schema
- `scripts/klc` — register subcommand
- `tests/integration/` — config validation, fake-client, link-building, intake modes
- `docs/process.md` — Jira section

## Open questions

None blocking. Existing `jira_sync.py` push path stays untouched in this
ticket (it is mirror-mode behaviour; managed comes in KLC-021).

## Estimate

- complexity: 3 (four new modules + intake integration + CLI namespace)
- uncertainty: 1 (Jira REST shapes; mitigated by fakeable client)
- risk: 1 (touches intake, a hot path)
- manual: 1 (verify against a real Jira issue once)
- total: 6 → **M**
