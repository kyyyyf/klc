#!/usr/bin/env python3
"""KLC-119 step-3 / KLC-174 step-5 (AC-8): every card render site goes through
`artefacts.render_card`, and NONE of them writes an `estimated` attempt any
more (real usage comes from `core/skills/token_import.py` / the provider envelope).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = FW_ROOT / "scripts"
KLC = SCRIPTS / "klc"
SKILLS_DIR = FW_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS_DIR))
sys.path.insert(0, str(FW_ROOT / "core" / "phases"))

import budget_guard  # noqa: E402
import token_journal  # noqa: E402


def _seed(tmp_path: Path, ticket: str, *, phase: str, track: str = "M",
          **extra) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    meta.update(extra)
    mp = tdir / "meta.json"
    mp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "spec.md").write_text(
        "## Goals\nfake\n## Acceptance Criteria\n- AC-1\n", encoding="utf-8")
    (tdir / "test-plan.md").write_text("fake\n", encoding="utf-8")
    return mp


def _all_attempts(ticket: str, phase: str) -> list[dict]:
    """Committed meta attempts UNION undrained journal attempts for one
    phase — a render site may land in either, depending on whether a
    transaction was open when it wrote (AC-4/AC-5)."""
    from _paths import klc_ticket_meta_file
    out: list[dict] = []
    mp = klc_ticket_meta_file(ticket)
    if mp.exists():
        meta = json.loads(mp.read_text(encoding="utf-8"))
        entry = meta.get("metrics", {}).get("tokens", {}).get(phase)
        out.extend(budget_guard.normalize_attempts(entry)["attempts"])
    for rec in token_journal.read(ticket):
        if rec.get("phase") == phase:
            out.append(rec)
    return out


@pytest.fixture(autouse=True)
def _reset_token_journal_state(monkeypatch):
    monkeypatch.setattr(token_journal, "_IGNORE_ENSURED", False)
    monkeypatch.setattr(token_journal, "_OPEN", set())


def _env(tmp_path: Path) -> dict:
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("KLC_CARD_ROOT", None)
    return env


# --------------------------------------------------------------------------- #
# klc_next
# --------------------------------------------------------------------------- #

def test_render_site_writes_no_estimated_attempt_klc_next(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    _seed(tmp_path, "KLC-RS-NEXT", phase="discovery:ack", track="M")
    env = _env(tmp_path)
    r = subprocess.run([sys.executable, str(KLC), "next", "KLC-RS-NEXT"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _all_attempts("KLC-RS-NEXT", "acceptance-test-plan") == []


# --------------------------------------------------------------------------- #
# klc_ack
# --------------------------------------------------------------------------- #

def test_render_site_writes_no_estimated_attempt_klc_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    _seed(tmp_path, "KLC-RS-ACK", phase="discovery:ack-needed", track="M")
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, str(KLC), "ack", "KLC-RS-ACK", "--pick", "1"],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _all_attempts("KLC-RS-ACK", "acceptance-test-plan") == []


# --------------------------------------------------------------------------- #
# klc_jump
# --------------------------------------------------------------------------- #

def test_render_site_writes_no_estimated_attempt_klc_jump(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    _seed(tmp_path, "KLC-RS-JUMP", phase="discovery:ack", track="M")
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, str(KLC), "jump", "design", "KLC-RS-JUMP", "--yes"],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _all_attempts("KLC-RS-JUMP", "design") == []


# --------------------------------------------------------------------------- #
# klc_step
# --------------------------------------------------------------------------- #

def test_render_site_writes_no_estimated_attempt_klc_step(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    _seed(tmp_path, "KLC-RS-STEP", phase="build:work", track="M")
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, str(KLC), "step", "KLC-RS-STEP", "1"],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _all_attempts("KLC-RS-STEP", "build") == []


# --------------------------------------------------------------------------- #
# autorunner (D-206)
# --------------------------------------------------------------------------- #

def test_render_site_writes_no_estimated_attempt_autorunner(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    _seed(tmp_path, "KLC-RS-AUTO", phase="review-lite:work", track="XS")

    import autorunner
    calls = []
    res = autorunner.run("KLC-RS-AUTO",
                         dispatch=lambda *a, **k: calls.append(a) or 0,
                         cap=1)
    assert calls, "the fake dispatch must have been invoked"
    assert _all_attempts("KLC-RS-AUTO", "review-lite") == []


# --------------------------------------------------------------------------- #
# run_dispatch (/klc:run)
# --------------------------------------------------------------------------- #

def test_render_site_writes_no_estimated_attempt_run_dispatch():
    """The prose orchestrator renders the card before dispatch and names the
    warn-only real-spend check, not the removed card-size gate."""
    text = (FW_ROOT / "klc-plugin" / "skills" / "go" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "render_card" in text
    assert "gate_card_dispatch" not in text
    assert "real_spend_warning" in text
    assert text.index("render_card") < text.index("Task(subagent_type=")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
