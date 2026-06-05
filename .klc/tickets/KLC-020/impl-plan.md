# KLC-020 impl-plan

## step-1 — jira.yml schema + validate_config.py

Extend `config/jira.yml` with new sections (`site`, `gitlab`, `status_mapping`,
`artifacts`, `mode`). Preserve existing `sync`/`url_template` untouched.
Update `validate_config.py` `KNOWN_SCHEMAS["jira.yml"]` to allow all new keys.

**Affected files**:
- `config/jira.yml`
- `core/skills/validate_config.py`

**Expected tests**:
- `python3 core/phases/doctor.py` → DOCTOR_OK
- `validate_config.validate_file(jira.yml)` → no warnings

**Rollback**: revert both files

---

## step-2 — jira_config.py: typed config + validation

New `core/skills/jira_config.py`. Exports `JiraConfig` dataclass and
`load(config_dir=None) -> JiraConfig`. Validates required fields; raises
`JiraConfigError` with field name on failure.

**Affected files**:
- `core/skills/jira_config.py` (new)

**Expected tests**:
- load valid config → JiraConfig object
- load with missing base_url → JiraConfigError naming field
- load with malformed blob_url template → JiraConfigError

**Rollback**: delete file

---

## step-3 — jira_client.py: Protocol + RestJiraClient + FakeJiraClient

New `core/skills/jira_client.py`. Defines `JiraClient` Protocol and two
implementations: `RestJiraClient` (urllib, no new deps) and `FakeJiraClient`
(in-memory, records calls). Module-level `make_client(cfg: JiraConfig)` factory.

**Affected files**:
- `core/skills/jira_client.py` (new)

**Expected tests**:
- FakeJiraClient: all methods callable, calls recorded
- RestJiraClient: missing auth env → RuntimeError with env var name
- make_client returns RestJiraClient when cfg has credentials

**Rollback**: delete file

---

## step-4 — jira_artifacts.py: GitLab links + idempotent comments

New `core/skills/jira_artifacts.py`. Exports `build_artifact_links()`,
`get_or_create_link_comment()`, `upsert_artifact_links()`.

Idempotency: scan issue comments for `<!-- klc:artifact-links KEY -->` marker;
update if found, create if not. gitlab.branch: read from config; if empty,
`git rev-parse --abbrev-ref HEAD`; fallback to "main".

**Affected files**:
- `core/skills/jira_artifacts.py` (new)

**Expected tests**:
- build_artifact_links: existing files → in table; missing → omitted
- upsert: first call → add_comment recorded; second call → update_comment recorded

**Rollback**: delete file

---

## step-5 — core/phases/jira.py + scripts/klc registration

New `core/phases/jira.py` implementing `klc jira status` and
`klc jira sync --dry-run|--apply`. Register `jira` in `scripts/klc`
dispatcher alongside `jira-sync`.

`status`: read-only, exits non-zero on mismatch. No prompts.
`sync`: prints/applies artefact links + updates meta.jira_sync block.

**Affected files**:
- `core/phases/jira.py` (new)
- `scripts/klc`

**Expected tests**:
- `klc jira status KEY` with FakeJiraClient returning matching status → exit 0
- `klc jira status KEY` with mismatch → exit 1, MISMATCH in stdout
- `klc jira status KEY` integration disabled → error message
- `klc jira sync KEY --dry-run` → prints plan, no client write calls

**Rollback**: delete jira.py; revert scripts/klc

---

## step-6 — intake.py: dup-check + description source + raw.md link

Modify `core/phases/intake.py`:
- After raw.md written, if integration enabled: GET issue.
- If issue exists: handle `--jira-description` flag or TTY prompt.
- Call `upsert_artifact_links` for raw.md comment (always, when integration on).
- Jira errors → log warning, never block intake.

**Affected files**:
- `core/phases/intake.py`

**Expected tests**:
- intake with `--jira-description jira` → raw.md has markers + Jira body
- intake with `--jira-description klc` → raw.md has NO markers
- intake with `--jira-description both` → raw.md has klc desc + marker section
- intake, Jira 404 → warning logged, intake succeeds normally
- intake, integration disabled → no Jira calls

**Rollback**: revert intake.py

---

## step-7 — docs/process.md + integration tests

Extend `docs/process.md` with a Jira integration section covering:
- enabling integration (`mode: mirror|managed`, jira.yml config)
- `klc jira status` / `sync` commands
- intake dup-check behaviour

Write `tests/integration/test_jira_core.py` covering all test cases from
the test-plan (AC-1..8 + edge cases), using FakeJiraClient throughout.

**Affected files**:
- `docs/process.md`
- `tests/integration/test_jira_core.py` (new)

**Expected tests**:
- `python3 tests/integration/test_jira_core.py` → ALL PASSED
- `python3 tests/e2e_pipeline.py` → unchanged
- `python3 core/phases/doctor.py` → DOCTOR_OK
