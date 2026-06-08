# KLC-021 impl-plan

## step-1 — config: managed_tickets + validate_config

Add `managed_tickets` optional list to `config/jira.yml`.
Update `validate_config.py` KNOWN_SCHEMAS["jira.yml"].

**Affected files**: `config/jira.yml`, `core/skills/validate_config.py`

**Expected tests**: doctor PASS, validate_file no warnings with managed_tickets.

---

## step-2 — jira_sync.py: SyncPlan + build_plan() + push()

Add `SyncPlan` dataclass. `build_plan(ticket, client, cfg) -> SyncPlan` — pure
read. `push(ticket, client, cfg) -> dict` — single-hop transition + comment.

Reuse `jira_config.load()`, `jira_client.make_client()` from KLC-020.

**Affected files**: `core/skills/jira_sync.py`

**Expected tests**:
- build_plan in-sync → in_sync=True
- build_plan klc-moved → target_status set, no conflict
- build_plan PM-moved → jira-moved-externally conflict
- push found transition → transition_issue + add_comment called
- push no transition → conflict, Jira NOT moved

---

## step-3 — lifecycle.py: mode-aware push_phase

Replace the simple `push_phase` call in `lifecycle.set_state` with a
mode-aware dispatcher. Mirror = calls old `push_phase` unchanged.
Managed = `_managed_push_phase(ticket, phase, cfg, client)`.

`_managed_push_phase`:
- build_plan; if in_sync → return
- TTY: prompt based on plan (klc-moved or PM-conflict)
- non-TTY: record divergence + stderr warn
- Never block; all paths return cleanly

TTY detection: `sys.stdin.isatty()` AND `sys.stdout.isatty()`.

**Affected files**: `core/skills/lifecycle.py`

**Expected tests**:
- mirror mode: existing e2e / smoke unchanged
- managed TTY klc-moved pick 1 → push called
- managed TTY klc-moved pick 2 → no push, no conflict
- managed TTY PM-conflict pick 1 → push back
- managed TTY PM-conflict pick 2 → divergence in meta
- managed TTY PM-conflict pick 3 → conflict in meta
- managed non-TTY divergence → conflict in meta, stderr warning
- Jira unreachable → ack completes, warning only

---

## step-4 — doctor.py: jira-sync-conflicts check

New `@check("jira-sync-conflicts")` function. Scans live tickets for
non-empty `meta.jira_sync.conflicts`. Returns errors list. Added to CHECKS
with `warn=True` (non-blocking by default, like project-tools).

**Affected files**: `core/phases/doctor.py`

**Expected tests**:
- ticket with conflicts → doctor shows WARN jira-sync-conflicts
- no conflicts → PASS

---

## step-5 — tests + docs

`tests/integration/test_jira_managed.py`: covers all AC-2..8 via
FakeJiraClient + mock TTY (monkeypatch sys.stdin/stdout.isatty).

`docs/process.md`: extend Jira section — managed mode, prompt UX, non-TTY,
conflict lifecycle.

**Affected files**: `tests/integration/test_jira_managed.py`, `docs/process.md`

**Expected tests**: all AC pass, e2e all tracks unchanged.
