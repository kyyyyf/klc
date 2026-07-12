"""KLC-052 step-4: stamp clarify_required on low-confidence intake.

The gate fires purely from route confidence, not from any judgment
about raw.md content quality — low confidence always sets the stamp,
high confidence never does, regardless of what was typed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import intake  # noqa: E402


def _run_intake(tmp_path, monkeypatch, ticket, desc, kind="tech"):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    rc = intake.run([ticket, "--kind", kind, desc])
    assert rc == 0
    meta_path = tmp_path / ".klc" / "tickets" / ticket / "meta.json"
    return json.loads(meta_path.read_text(encoding="utf-8"))


def test_low_confidence_always_fires_gate(tmp_path, monkeypatch):
    # Short, no keyword/module signal → low confidence (route_heuristic).
    meta = _run_intake(tmp_path, monkeypatch, "KLC-9001", "make it better")
    assert meta["route_confidence"] == "low"
    assert meta["clarify_required"] is True


def test_high_confidence_gate_does_not_fire(tmp_path, monkeypatch):
    long_desc = " ".join(["word"] * 120)  # word_count >= 100 -> high confidence
    meta = _run_intake(tmp_path, monkeypatch, "KLC-9002", long_desc)
    assert meta["route_confidence"] == "high"
    assert meta.get("clarify_required") in (False, None)


def test_gate_fires_without_requiring_user_content(tmp_path, monkeypatch):
    # Different short, content-free descriptions still fire the gate
    # identically — the stamp depends only on confidence, not on what
    # was typed.
    meta_a = _run_intake(tmp_path, monkeypatch, "KLC-9003", "fix it")
    meta_b = _run_intake(tmp_path, monkeypatch, "KLC-9004", "asdf qwer")
    assert meta_a["clarify_required"] is True
    assert meta_b["clarify_required"] is True


def test_nothing_to_add_satisfies_gate():
    # AC-10: "nothing to add" is a valid, complete answer that clears
    # the gate — mandatory means the gate always *fires*, not that the
    # human must produce content. Documented in the clarify pass itself
    # (core/agents/intake-triage.md), since clearing the gate is a
    # main-loop/agent action, not something intake.py's stamp enforces.
    text = (_FW_ROOT / "core" / "agents" / "intake-triage.md").read_text(encoding="utf-8")
    assert "nothing to add" in text.lower()
    assert "satisfies the gate" in text.lower() or "clears the gate" in text.lower() \
        or "clear the gate" in text.lower()
