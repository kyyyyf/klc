---
ticket: KLC-020
phase: review
authority: agent
verdict: CHANGES REQUESTED
---

# KLC-020 review report

## Summary

CHANGES REQUESTED. This pass found blocking issues in security, architecture,
and test coverage. Performance review found no issues.

ISSUES_TOTAL=11 ISSUES_BLOCKING=10

---

## Blocking Issues

### [HIGH] Non-HTTPS Jira base_url can receive auth tokens - core/skills/jira_config.py:124

`site.base_url` is only checked for being non-empty, then flows into
`RestJiraClient`, which sends an `Authorization` header on every request. A
project override can set `enabled: true` with `site.base_url: http://...`,
causing Jira PAT/Basic credentials to be sent over cleartext.

Fix: validate `site.base_url` in `jira_config.load()` with
`urllib.parse.urlparse`; require `scheme == "https"` and a hostname before
constructing `JiraConfig`.

### [HIGH] Legacy Jira sync mapping was changed instead of preserved - config/jira.yml:119

The legacy `sync.phase_to_status` block now uses the new KLC-020 statuses,
while the spec says the existing `jira_sync.py` push path stays untouched and
the impl-plan says to preserve existing `sync`/`url_template`. `jira_sync.py`
still reads this block for lifecycle auto-pushes, so existing mirror-mode
setups can inherit changed Jira transitions.

Fix: restore legacy `sync.phase_to_status` values and keep new mappings only
under `status_mapping.klc_to_jira`, unless the spec explicitly migrates legacy
sync semantics.

### [HIGH] KLC-020 exposes state-changing Jira reconciliation - core/phases/jira.py:221

`_reconcile_push` calls `client.transition_issue`, adds a provenance comment,
and writes `meta.jira_sync`. KLC-020 is specified as the side-effect-free /
read-only foundation, with push/pull state changes deferred to KLC-021/022.

Fix: remove or disable `klc jira reconcile push` in KLC-020, or make it return
a deferred/not-implemented message until KLC-021 owns the state-changing path.

### [HIGH] Comment upsert writes after comment-read failure - core/skills/jira_artifacts.py:70

`_find_link_comment` catches any `RuntimeError` from `get_issue_comments` and
returns `(None, None)`. `upsert_artifact_links` then treats an unknown comment
state as "no marker exists" and calls `add_comment`, which can duplicate marker
comments after transient read failures. This contradicts AC-8's "never
duplicates" idempotency contract.

Fix: propagate comment-list failures and let callers warn/fail non-fatally
without writing. Only create a new comment after comments were successfully
listed and no marker was found.

### [HIGH] Config schema and mapping validation coverage is incomplete - tests/integration/test_jira_core.py:75

AC-1/AC-2 are only partially covered. Current Jira tests cover valid load,
missing `base_url`, missing `auth_env`, and malformed `blob_url`, but there is
no test for `validate_config.validate_file(config/jira.yml)`, `klc doctor` with
the new Jira keys, unknown Jira config keys, or missing
`status_mapping.klc_to_jira` / `jira_to_klc`.

Fix: add focused config tests for `validate_config.py` plus negative
`jira_config.load()` cases for both missing mappings.

### [HIGH] AC-3 client method coverage is incomplete - tests/integration/test_jira_core.py:149

The fakeable client contract requires `get_issue`, `get_transitions`,
`transition_issue`, `add_comment`, and `get_current_user`. Tests cover
`get_issue`, `add_comment` / `update_comment`, and missing auth env, but not
`get_transitions`, `transition_issue`, `get_current_user`, or `make_client`.

Fix: add tests that assert `FakeJiraClient` returns/records transitions,
transition calls, current user, and that `make_client(cfg)` builds a
`RestJiraClient`.

### [HIGH] Artefact link URL contract is only partially asserted - tests/integration/test_jira_core.py:200

AC-4 requires GitLab blob links to use the configured
`{base_url}/-/blob/{branch}/{path}` template. The current test checks that an
existing artefact appears and a missing one is omitted, but it does not assert
the exact generated URL/path.

Fix: assert the full expected URL, including base URL, branch, and
`.klc/tickets/<KEY>/<path>`.

### [HIGH] `klc jira status` success/mismatch/read-only paths are uncovered - tests/integration/test_jira_core.py:258

AC-5 requires `klc jira status <KEY>` to print KLC phase, Jira status, emit
`MISMATCH` when mappings differ, and remain read-only. The only current status
test covers the disabled-config error path.

Fix: add fake-client tests for matching status exit 0, mismatch exit 1 with
`MISMATCH`, and no transition/comment/write calls.

### [HIGH] Intake Jira enrichment has no acceptance coverage - core/phases/intake.py:228

AC-6/AC-7 require intake dup-check, `--jira-description` modes, Jira
description markers in `raw.md`, non-blocking 404/403 behavior, and a raw.md
Jira comment with `moved by klc` provenance. No tests exercise
`_jira_intake_enrich` or the intake CLI with Jira enabled.

Fix: add intake tests using `FakeJiraClient` for `klc`, `jira`, and `both`
description modes, missing/forbidden Jira issues, non-TTY default, and raw.md
link comment creation.

---

## Non-Blocking Issues

### [MEDIUM] Artifact paths can escape ticket directory - core/skills/jira_artifacts.py:37

`rel_path` from `cfg.artifact_paths` is joined directly as
`ticket_dir / rel_path` with no absolute-path rejection, `..` rejection, or
resolved containment check. Because existing paths are converted into Jira
artifact-link comments, a bad project config can publish links for files outside
`.klc/tickets/<KEY>` instead of only ticket artefacts.

Fix: resolve each candidate path and require it to stay under
`ticket_dir.resolve()` before including it.

### [MEDIUM] Intake treats all Jira lookup errors as missing issues - core/phases/intake.py:255

`client.get_issue` failures are all caught as `RuntimeError` and converted to
`jira_exists = False`. That makes 403/auth/timeouts indistinguishable from 404,
suppresses the required warning, and skips the raw.md link upsert path.

Fix: introduce typed Jira errors or status-aware helpers so only 404 means
"missing"; all other Jira errors should warn and avoid follow-up writes.

---

## Reviewer Partials

### Security

ISSUES_TOTAL=2 ISSUES_BLOCKING=1

### Architecture

ISSUES_TOTAL=4 ISSUES_BLOCKING=3

### Performance

No issues found.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0

### Test Coverage

ISSUES_TOTAL=5 ISSUES_BLOCKING=5

---

## Verification Run

These checks were run during review and passed:

- `python3 tests/integration/test_jira_core.py`
- `python3 tests/e2e_pipeline.py`
- `python3 core/phases/doctor.py`
- `python3 -m py_compile core/skills/jira_config.py core/skills/jira_client.py core/skills/jira_artifacts.py core/phases/jira.py core/phases/intake.py core/skills/validate_config.py`
- `validate_config.validate_file(config/jira.yml)` returned `[]`

## Verdict

**CHANGES REQUESTED** - blocking findings were found and not fixed during this
review pass.
