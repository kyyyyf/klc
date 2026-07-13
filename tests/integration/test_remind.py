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
