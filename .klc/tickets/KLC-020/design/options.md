---
ticket: KLC-020
phase: design
authority: agent
---

# KLC-020 — Design

One implementation option only. No architectural alternatives.

## Option A — adopted (only option)

### Module layout

```
config/jira.yml                   (extend existing)
core/skills/jira_config.py        (new: load+validate jira.yml)
core/skills/jira_client.py        (new: fakeable REST client)
core/skills/jira_artifacts.py     (new: build GitLab link table)
core/phases/jira.py               (new: CLI handler for klc jira ...)
core/phases/intake.py             (modify: dup-check + description modes)
core/skills/validate_config.py    (modify: extend jira.yml schema)
scripts/klc                       (modify: register jira subcommand)
tests/integration/test_jira_*.py  (new)
docs/process.md                   (extend Jira section)
```

Existing `core/skills/jira_sync.py` is **NOT touched** — it owns the
push-on-set_state path (mirror mode). KLC-020 only adds the new modules
alongside it.

### jira.yml schema extension

New top-level keys added (existing `sync` and `url_template` preserved):

```yaml
mode: mirror       # mirror | managed (KLC-021 activates managed)

site:
  base_url: "https://jira.example.com"
  project_key: "KLC"
  auth_env: "JIRA_API_TOKEN"
  auth_user_env: ""   # optional; if set, Basic auth instead of Bearer

gitlab:
  base_url: "https://gitlab.example.com/group/repo"
  branch: "main"      # or leave blank to auto-detect from git
  blob_url: "{base_url}/-/blob/{branch}/{path}"

status_mapping:
  klc_to_jira:         # same content as existing phase_to_status (rename/alias)
    intake: "Backlog"
    discovery: "Discovery"
    # ... etc
  jira_to_klc:         # new: for pull resolution (KLC-022)
    "Backlog": [intake]
    "Discovery": [discovery]
    "In Progress": [xs-build, build]
    # ... etc

artifacts:
  comment_links: true
  paths:
    raw: "raw.md"
    spec: "spec.md"
    test_plan: "test-plan.md"
    design: "design/options.md"
    impl_plan: "impl-plan.md"
    build_log: "build-log.md"
    review: "review-report.md"
    review_lite: "review-lite-report.md"
    manual: "manual-checklist.md"
    integrate: "integrate.md"
    observe: "observe.md"
    retrospective: "retrospective.md"
```

The existing `sync.phase_to_status` stays (used by old jira_sync.py push
path). `status_mapping.klc_to_jira` is the new canonical form for new code.

### jira_config.py — typed config + validation

```python
@dataclass
class JiraConfig:
    enabled: bool
    mode: str          # "mirror" | "managed"
    base_url: str
    project_key: str
    auth_env: str
    auth_user_env: str
    gitlab_base_url: str
    gitlab_branch: str
    gitlab_blob_url_tmpl: str
    klc_to_jira: dict[str, str]
    jira_to_klc: dict[str, list[str]]
    artifact_paths: dict[str, str]
    comment_links: bool

def load(config_dir: Path | None = None) -> JiraConfig: ...
```

Validation: base_url non-empty, auth_env non-empty, both mappings present,
blob_url template contains `{base_url}`, `{branch}`, `{path}`.

### jira_client.py — injectable client

```python
class JiraClient(Protocol):
    def get_issue(self, key: str) -> dict: ...
    def get_transitions(self, key: str) -> list[dict]: ...
    def transition_issue(self, key: str, transition_id: str,
                         fields: dict | None = None) -> None: ...
    def add_comment(self, key: str, body: str) -> dict: ...
    def update_comment(self, key: str, comment_id: str, body: str) -> None: ...
    def get_issue_comments(self, key: str) -> list[dict]: ...
    def get_current_user(self) -> dict: ...

class RestJiraClient:
    """Real implementation via urllib (no new deps)."""

class FakeJiraClient:
    """In-process fake for tests. Records calls, returns canned data."""
    calls: list[tuple[str, tuple, dict]]
    issues: dict[str, dict]       # key → issue response
    transitions: dict[str, list]  # key → transitions list
```

`FakeJiraClient` is injected via a module-level `_get_client()` factory
that can be overridden in tests — same pattern as `_DISPATCH` in runner.py.

### jira_artifacts.py

```python
COMMENT_MARKER = "<!-- klc:artifact-links {key} -->"

def build_artifact_links(ticket: str, cfg: JiraConfig) -> str:
    """Return markdown link table for existing artefacts."""

def get_or_create_link_comment(client: JiraClient, key: str,
                                body: str) -> tuple[str, bool]:
    """Find existing marker comment and return (comment_id, is_new).
    Idempotent: finds by marker, never duplicates."""

def upsert_artifact_links(client: JiraClient, key: str,
                           ticket: str, cfg: JiraConfig) -> None:
    """Build links and add/update the marker comment."""
```

Idempotency: scan issue comments for `COMMENT_MARKER.format(key=key)`;
if found → update_comment; if not → add_comment.

### jira.py CLI

```bash
klc jira status <KEY>        # read-only
klc jira sync <KEY> [--dry-run | --apply]  # report + links, no state change
```

`status`: calls `jira_config.load()`, `JiraClient.get_issue()`, compares
`klc_to_jira[current_phase]` vs Jira status. Exits non-zero on mismatch.
No prompts, no writes.

`sync --dry-run`: prints sync plan (what links would be added/updated).
`sync --apply`: calls `upsert_artifact_links()`, updates meta.jira_sync.

### intake.py changes

After raw.md is written, if `jira_config.load().enabled`:
1. GET issue. If Jira returns 404/403 → log warning, continue (not a hard block).
2. If issue exists and `--jira-description klc` (default) → no change to raw.md.
   If `jira` → write Jira description inside markers.
   If `both` → append Jira section after existing klc description.
3. Call `upsert_artifact_links(client, key, ticket, cfg)` for raw.md link.

Non-interactive flag: `--jira-description klc|jira|both`.
Interactive (TTY, no flag): prompt with numbered choice.
Non-TTY without flag: default `klc`, warning to stderr.

[!DECISION D-001] jira_client is injected via factory, not imported directly,
so tests can swap FakeJiraClient without monkeypatching.
[!DECISION D-002] Jira errors on intake are warnings, not hard failures —
integration must not block the core klc workflow.
[!DECISION D-003] gitlab.branch auto-detects from `git rev-parse --abbrev-ref HEAD`
when config value is empty/absent; defaults to "main" if git fails.
