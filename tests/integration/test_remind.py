#!/usr/bin/env python3
"""Tests for `klc remind` — the silent-by-default forgotten-ack advisory (KLC-059).

`klc remind` emits exactly one line per ticket that the current git identity
holds in a `<phase>:work` state AND for which
`phase_completion.can_complete(ticket, phase)` returns True.  It is silent
otherwise and always exits 0.

Test setup uses a temp PROJECT_ROOT with fabricated tickets.  A ticket parked
in `integrate:work` genuinely satisfies `can_complete` because the `integrate`
phase declares no outputs (see config/phases.yml), so the generic completion
check returns True without any artefacts to fabricate.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent.parent
PHASES_DIR = FW_ROOT / "core" / "phases"
SKILLS_DIR = FW_ROOT / "core" / "skills"
PLUGIN_DIR = FW_ROOT / "klc-plugin"
KLC = FW_ROOT / "scripts" / "klc"


def _load_remind():
    """Import core/phases/remind.py as a standalone module."""
    if str(SKILLS_DIR) not in sys.path:
        sys.path.insert(0, str(SKILLS_DIR))
    path = PHASES_DIR / "remind.py"
    spec = importlib.util.spec_from_file_location("klc_phase_remind", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fabricate_ticket(root: Path, ticket: str, *, phase: str,
                      holder_id: str | None, track: str = "M") -> None:
    """Write a minimal meta.json for a fabricated ticket."""
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": phase,
        "phase_history": [],
        "track": track,
        "affected_modules": [],
        "estimate": None,
        "created": "2026-01-01T00:00:00Z",
    }
    if holder_id is not None:
        meta["holder"] = {
            "id": holder_id,
            "machine": "test-machine",
            "since": "2026-01-01T00:00:00Z",
        }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


ID = "tester@example.com"


def _fabricate_completable_discovery(root: Path, ticket: str, *,
                                     holder_id: str,
                                     phase: str = "discovery:work") -> Path:
    """Fabricate a discovery ticket that passes every discovery gate.

    Returns the meta.json path. Used by KLC-062 to prove `klc remind` does not
    rewrite meta.json (via the `_sync_risk_tags` write inside
    `can_complete_discovery`). track == route_hint == M so the floor guard is
    skipped and no modules.json is needed.

    `phase` may be an on-disk LEGACY string (e.g. ``discovery-running`` →
    ``discovery:work``) to exercise the migration-write-back path.
    """
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "bug",
        "phase": phase,
        "phase_history": [],
        "track": "M",
        "route_hint": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1,
                     "manual": 1, "total": 5},
        "layer": "code",
        "affected_modules": ["core/skills"],
        "created": "2026-01-01T00:00:00Z",
        "holder": {"id": holder_id, "machine": "test-machine",
                   "since": "2026-01-01T00:00:00Z"},
    }
    (tdir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    spec = (
        "---\n"
        f"ticket: {ticket}\n"
        "kind: bug\n"
        "authority: human\n"
        "risk_tags: [data]\n"
        "---\n\n"
        f"# {ticket} — completable discovery fixture\n\n"
        "## Goals\n\nMake the thing read-only.\n\n"
        "## Acceptance Criteria\n\n1. AC-1: given X, when Y, then Z.\n\n"
        "## Approaches considered\n\n"
        "- Approach A — keyword flag: gate the write behind a defaulted keyword.\n"
        "- Approach B — relocate: move the write to the ack path.\n\n"
        "Picked: Approach A — smallest blast radius.\n\n"
        "## Estimate\n\n"
        "- complexity: 2\n- uncertainty: 1\n- risk: 1\n- manual: 1\n"
        "- total: 5\n- track: M\n"
    )
    (tdir / "spec.md").write_text(spec, encoding="utf-8")
    return tdir / "meta.json"


def test_remind_silent_when_nothing_to_do(tmp_path, monkeypatch, capsys):
    """AC-1: no completable-held ticket → no output, exit 0."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    (tmp_path / ".klc" / "tickets").mkdir(parents=True)
    remind = _load_remind()
    monkeypatch.setattr(remind, "_git_user", lambda: ID)

    rc = remind.run([])

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_remind_fires_when_held_and_completable(tmp_path, monkeypatch, capsys):
    """AC-2: current identity holds a :work phase that can_complete → one line."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    # integrate has no declared outputs → can_complete returns True.
    _fabricate_ticket(tmp_path, "KLC-901", phase="integrate:work", holder_id=ID)
    remind = _load_remind()
    monkeypatch.setattr(remind, "_git_user", lambda: ID)

    rc = remind.run([])

    assert rc == 0
    out = capsys.readouterr().out
    assert out == "KLC-901 integrate is done — run klc ack\n"


def test_remind_silent_for_other_holder(tmp_path, monkeypatch, capsys):
    """AC-3: ticket held by a different identity → silently skipped."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _fabricate_ticket(tmp_path, "KLC-902", phase="integrate:work",
                      holder_id="someone-else@example.com")
    remind = _load_remind()
    monkeypatch.setattr(remind, "_git_user", lambda: ID)

    rc = remind.run([])

    assert rc == 0
    assert capsys.readouterr().out == ""


# --- step-2: hook delivery + statusline (AC-4, AC-5) -------------------------

HOOK_REMIND = PLUGIN_DIR / "hooks" / "remind.py"


def _klc_bin_env(project_root: Path) -> dict[str, str]:
    env = {**os.environ, "PROJECT_ROOT": str(project_root)}
    env["KLC_BIN"] = f"{sys.executable} {KLC}"
    return env


def test_hooks_json_has_remind_entry():
    """AC-4: hooks.json registers a UserPromptSubmit hook invoking remind.py."""
    hooks_json = PLUGIN_DIR / "hooks" / "hooks.json"
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    entries = data["hooks"]["UserPromptSubmit"]
    commands = [
        h["command"]
        for group in entries
        for h in group.get("hooks", [])
    ]
    assert any("remind.py" in c for c in commands), (
        f"no UserPromptSubmit hook invokes remind.py; commands={commands!r}"
    )


def test_hook_always_exits_zero(tmp_path):
    """AC-4: the hook exits 0 even when klc cannot locate a ticket."""
    # Empty PROJECT_ROOT with no .klc — remind finds nothing.
    env = _klc_bin_env(tmp_path)
    result = subprocess.run(
        [sys.executable, str(HOOK_REMIND)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, (
        f"hook must exit 0 (non-blocking); stderr={result.stderr!r}"
    )

    # Even with a broken KLC_BIN (klc not found) the hook swallows the error.
    env_broken = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env_broken["KLC_BIN"] = "/nonexistent/klc-binary-xyz"
    result2 = subprocess.run(
        [sys.executable, str(HOOK_REMIND)],
        capture_output=True, text=True, env=env_broken,
    )
    assert result2.returncode == 0, (
        f"hook must exit 0 even when klc is missing; stderr={result2.stderr!r}"
    )


def test_statusline_flag_emits_same_line(tmp_path):
    """AC-5: `klc remind --statusline` emits the same line as `klc remind`."""
    remind = _load_remind()
    identity = remind._git_user()
    _fabricate_ticket(tmp_path, "KLC-903", phase="integrate:work",
                      holder_id=identity)
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}

    plain = subprocess.run(
        [sys.executable, str(KLC), "remind"],
        capture_output=True, text=True, env=env,
    )
    statusline = subprocess.run(
        [sys.executable, str(KLC), "remind", "--statusline"],
        capture_output=True, text=True, env=env,
    )

    assert plain.returncode == 0 and statusline.returncode == 0
    expected = "KLC-903 integrate is done — run klc ack\n"
    assert plain.stdout == expected, f"plain stdout={plain.stdout!r}"
    assert statusline.stdout == expected, (
        f"statusline stdout={statusline.stdout!r}"
    )


# --- review-fix: robustness (P2a, P2b) ---------------------------------------


def _write_meta_raw(root: Path, ticket: str, meta: dict) -> None:
    """Write an arbitrary meta.json (used to fabricate corrupt tickets)."""
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_remind_skips_non_dict_holder(tmp_path, monkeypatch, capsys):
    """P2a: a ticket with a non-dict `holder` must not abort the scan.

    One malformed ticket (holder is a string) plus one legitimately
    completable held ticket → remind prints the good one and exits 0
    with no traceback.
    """
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    # Malformed: holder is a bare string, not a dict.
    _write_meta_raw(tmp_path, "KLC-800", {
        "ticket": "KLC-800",
        "kind": "feature",
        "phase": "integrate:work",
        "phase_history": [],
        "track": "M",
        "affected_modules": [],
        "estimate": None,
        "created": "2026-01-01T00:00:00Z",
        "holder": "corrupt-not-a-dict",
    })
    # Legit completable held ticket (sorts after KLC-800).
    _fabricate_ticket(tmp_path, "KLC-901", phase="integrate:work", holder_id=ID)
    remind = _load_remind()
    monkeypatch.setattr(remind, "_git_user", lambda: ID)

    rc = remind.run([])

    assert rc == 0
    assert capsys.readouterr().out == "KLC-901 integrate is done — run klc ack\n"


def test_hook_swallows_child_failure_stderr(tmp_path):
    """P2b: when `klc remind` exits non-zero with stderr, the hook stays silent."""
    fake = tmp_path / "fake_klc.py"
    fake.write_text(
        "import sys\n"
        "sys.stderr.write('BOOM traceback leak\\n')\n"
        "sys.stdout.write('SHOULD-NOT-LEAK\\n')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env["KLC_BIN"] = f"{sys.executable} {fake}"
    result = subprocess.run(
        [sys.executable, str(HOOK_REMIND)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0
    assert result.stderr == "", f"child stderr leaked: {result.stderr!r}"
    assert result.stdout == "", f"child stdout leaked on failure: {result.stdout!r}"


def test_hook_forwards_child_stdout_on_success(tmp_path):
    """P2b: when `klc remind` exits 0 with a reminder line, it reaches stdout."""
    fake = tmp_path / "fake_klc.py"
    fake.write_text(
        "import sys\n"
        "sys.stdout.write('KLC-777 integrate is done — run klc ack\\n')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env["KLC_BIN"] = f"{sys.executable} {fake}"
    result = subprocess.run(
        [sys.executable, str(HOOK_REMIND)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0
    assert result.stdout == "KLC-777 integrate is done — run klc ack\n"
    assert result.stderr == ""


# --- review-fix2: operate relative to PROJECT_ROOT, not cwd (P2a, P2b) -------


def _git_init(path: Path, email: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", email], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def test_remind_uses_project_root_not_cwd(tmp_path):
    """P2a/P2b: hook runs from an arbitrary cwd with PROJECT_ROOT set.

    Identity and the completion check must target the PROJECT repo, not the
    caller's cwd. The project's local git identity differs from the cwd's, and
    the held ticket is recorded with the project identity → reminder must fire.
    """
    project = tmp_path / "project"
    other = tmp_path / "elsewhere"
    _git_init(project, "project@example.com")
    _git_init(other, "caller@example.com")

    _fabricate_ticket(project, "KLC-950", phase="integrate:work",
                      holder_id="project@example.com")

    env = {**os.environ, "PROJECT_ROOT": str(project)}
    # Ensure no ambient identity masks the bug.
    env.pop("GIT_AUTHOR_EMAIL", None)
    env.pop("GIT_COMMITTER_EMAIL", None)

    result = subprocess.run(
        [sys.executable, str(KLC), "remind"],
        capture_output=True, text=True, env=env, cwd=str(other),
    )

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert result.stdout == "KLC-950 integrate is done — run klc ack\n", (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# --- review-fix3: no Jira side effect + non-string phase (P2a, P2b) ----------


def test_remind_does_not_drain_jira_queue(tmp_path):
    """P2a: `klc remind` is advisory-only — it must not drain the Jira queue.

    Jira sync is enabled so that if the dispatcher's opportunistic drain ran,
    `flush_queue` would rewrite the queue (push fails without a token →
    canonical json.dumps reformat) and change its bytes. The queue line is
    written in a non-canonical form (no spaces) so any drain-rewrite is
    detectable. Post-fix `remind` skips the drain → the file is byte-identical.
    """
    (tmp_path / ".klc" / "tickets").mkdir(parents=True)
    cfg_dir = tmp_path / ".klc" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "jira.yml").write_text(
        "sync:\n  enabled: true\n  transport: rest\n", encoding="utf-8"
    )
    queue = tmp_path / ".klc" / "jira-queue.jsonl"
    # Non-canonical (no spaces): a drain-rewrite via json.dumps would reformat.
    payload = '{"ticket":"KLC-999","status":"In Progress","phase":"build:work"}\n'
    queue.write_text(payload, encoding="utf-8")

    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("JIRA_TOKEN", None)  # ensure push would fail (no drain expected anyway)
    result = subprocess.run(
        [sys.executable, str(KLC), "remind"],
        capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert queue.exists(), "remind deleted the Jira queue"
    assert queue.read_text(encoding="utf-8") == payload, (
        "remind mutated the Jira queue (unexpected drain side effect)"
    )


def test_remind_does_not_write_meta_for_completable_discovery(
    tmp_path, monkeypatch, capsys
):
    """KLC-062 AC-1/AC-4: `klc remind` on a completable `discovery:work` ticket
    held by the caller must fire the reminder AND leave meta.json byte-identical.

    Today `can_complete_discovery` calls `_sync_risk_tags`, which rewrites
    meta.json → per-prompt git-dirty churn. Post-fix the probe runs with
    persist=False so no write happens.
    """
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    meta_p = _fabricate_completable_discovery(tmp_path, "KLC-905", holder_id=ID)
    before = meta_p.read_bytes()
    remind = _load_remind()
    monkeypatch.setattr(remind, "_git_user", lambda: ID)

    rc = remind.run([])

    assert rc == 0
    assert capsys.readouterr().out == "KLC-905 discovery is done — run klc ack\n"
    assert meta_p.read_bytes() == before, (
        "remind rewrote meta.json for a completable discovery ticket "
        "(_sync_risk_tags side effect must be suppressed on the read-only path)"
    )


def test_remind_does_not_write_meta_legacy_discovery_phase(
    tmp_path, monkeypatch, capsys
):
    """KLC-062 FINDING-1: `klc remind` must not persist a legacy-phase migration
    even when the phase maps to a WRITE-CAPABLE completion checker (discovery).

    A completable ticket whose on-disk phase is the legacy `discovery-running`
    (→ `discovery:work`) routes through `can_complete_discovery`, which loads meta
    via `read_meta`. Unless that read is also read-only, the migration is written
    back → AC-2 breach. This fixture fails before the FINDING-1 fix (read_meta
    persists the migration) and passes after.
    """
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    meta_p = _fabricate_completable_discovery(
        tmp_path, "KLC-908", holder_id=ID, phase="discovery-running"
    )
    before = meta_p.read_bytes()
    remind = _load_remind()
    monkeypatch.setattr(remind, "_git_user", lambda: ID)

    rc = remind.run([])

    assert rc == 0
    assert capsys.readouterr().out == "KLC-908 discovery is done — run klc ack\n"
    assert meta_p.read_bytes() == before, (
        "remind persisted a legacy→discovery migration via can_complete_discovery's "
        "internal read_meta (must be read-only on the advisory path)"
    )


def test_remind_does_not_write_meta_legacy_phase(tmp_path, monkeypatch, capsys):
    """KLC-062 AC-2: `klc remind` must not persist a legacy-phase migration.

    A ticket whose phase is a legacy string (`integrate-post` → `integrate:work`)
    that the caller holds is completable (integrate declares no outputs), so the
    reminder fires — but meta.json must stay byte-identical (no read_meta
    write-back on the advisory path).
    """
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_meta_raw(tmp_path, "KLC-906", {
        "ticket": "KLC-906",
        "kind": "feature",
        "phase": "integrate-post",  # legacy → integrate:work
        "phase_history": [],
        "track": "M",
        "affected_modules": [],
        "estimate": None,
        "created": "2026-01-01T00:00:00Z",
        "holder": {"id": ID, "machine": "m", "since": "2026-01-01T00:00:00Z"},
    })
    meta_p = tmp_path / ".klc" / "tickets" / "KLC-906" / "meta.json"
    before = meta_p.read_bytes()
    remind = _load_remind()
    monkeypatch.setattr(remind, "_git_user", lambda: ID)

    rc = remind.run([])

    assert rc == 0
    assert capsys.readouterr().out == "KLC-906 integrate is done — run klc ack\n"
    assert meta_p.read_bytes() == before, (
        "remind persisted a legacy-phase migration (must be read-only)"
    )


def test_remind_skips_non_string_phase(tmp_path, monkeypatch, capsys):
    """P2b: a ticket with a non-string `phase` must not abort the scan."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    # Malformed: phase is an int, not a string.
    _write_meta_raw(tmp_path, "KLC-810", {
        "ticket": "KLC-810",
        "kind": "feature",
        "phase": 123,
        "phase_history": [],
        "track": "M",
        "affected_modules": [],
        "estimate": None,
        "created": "2026-01-01T00:00:00Z",
        "holder": {"id": ID, "machine": "m", "since": "2026-01-01T00:00:00Z"},
    })
    # Legit completable held ticket (sorts after KLC-810).
    _fabricate_ticket(tmp_path, "KLC-901", phase="integrate:work", holder_id=ID)
    remind = _load_remind()
    monkeypatch.setattr(remind, "_git_user", lambda: ID)

    rc = remind.run([])

    assert rc == 0
    assert capsys.readouterr().out == "KLC-901 integrate is done — run klc ack\n"
