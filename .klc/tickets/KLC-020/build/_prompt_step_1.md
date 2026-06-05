# Agent prompt — KLC-020 · build:work · step-1

Ticket: **KLC-020** · track: **M** · kind: **feature**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Build the side-effect-free foundation of the `klc jira` namespace: config,
fakeable REST client, GitLab artefact links, `klc jira status` (read-only),
and intake duplicate-check. No state changes to klc or Jira phases — that
is KLC-021/022. This is part 1 of 3.

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

### Current step — step-1

**jira.yml schema + validate_config.py**

Extend `config/jira.yml` with new sections (`site`, `gitlab`, `status_mapping`,
`artifacts`, `mode`). Preserve existing `sync`/`url_template` untouched.
Update `validate_config.py` `KNOWN_SCHEMAS["jira.yml"]` to allow all new keys.

**Affected files**:

- `config/jira.yml`

- `core/skills/validate_config.py`


**Expected tests**:

- `python3 core/phases/doctor.py`



**Rollback**: revert both files


### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/mnt/d/a_work/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-020 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-020/impl-plan.md`
- Full spec: `.klc/tickets/KLC-020/spec.md`
- Full test-plan: `.klc/tickets/KLC-020/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-020 step-1` and
run `klc step KLC-020 2` to get the next step's card,
or `klc ack KLC-020 --pick 1` if this was the last step.
