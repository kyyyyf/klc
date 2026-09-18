#!/usr/bin/env python3
"""KLC-117 step-4 — AC-8: the phase-history note stays within 200 characters.

Drives the REAL manual-completion path in `core/phases/ack.py` (single-user /
feature-OFF, so no git machinery is involved) with `phase_completion.can_complete`
monkeypatched to return a deliberately long advisory string, proving `ack.py`
caps the note rather than concatenating it unbounded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "core" / "phases"))

import advisories  # noqa: E402


def _seed_ticket(tmp_path: Path, ticket: str) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery:work",
        "phase_history": [], "track": "M", "route_hint": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 1, "total": 5},
        "layer": "code", "affected_modules": ["core/skills"],
        "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def test_note_within_cap_for_manual_completion_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-CAP1"
    _seed_ticket(tmp_path, ticket)

    import ack as ack_mod

    long_summary = "0 high · 0 medium · 40 info — see " + ("x" * 140)
    monkeypatch.setattr(ack_mod.phase_completion, "can_complete",
                        lambda t, pid, persist=True: (True, long_summary))

    # The manual-completion transition writes the note and recurses into
    # ack-needed, which then needs a --pick (a separate, unrelated concern) —
    # rc may be non-zero for THAT reason, but the note is already persisted.
    ack_mod.run([ticket])

    meta = json.loads((tmp_path / ".klc" / "tickets" / ticket / "meta.json").read_text())
    note = meta["phase_history"][-1]["note"]
    assert len(note) <= advisories.NOTE_CAP
    assert note.endswith(long_summary)
