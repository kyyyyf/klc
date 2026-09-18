#!/usr/bin/env python3
"""KLC-116 step-2 — AC-6's real-hook-boundary regression twins.

Design addendum revision 2 (F-004, D-010): `consistency_check.py --ticket
KLC-102` exits **1 today**, before any KLC-116 change, on
`orphan_questions: ["Q-001"]` — unrelated to provenance. The honest property
this ticket adds is: the gate produces NO provenance finding for KLC-102, and
its error list is byte-identical to the pre-existing baseline. KLC-094 is the
real ticket verified green today, kept as the real green-to-green regression.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import consistency_check  # noqa: E402
import provenance  # noqa: E402


def test_precommit_over_legacy_ticket_exits_zero(monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(FW_ROOT))
    ticket = "KLC-102"
    baseline = [
        f"{ticket}: items.validate: orphan_questions: [\"Q-001\"]",
    ]
    errs = consistency_check.check_ticket(ticket)
    assert errs == baseline
    assert provenance.check_artefacts(ticket) == []


def test_green_legacy_ticket_still_exits_zero(monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(FW_ROOT))
    ticket = "KLC-094"
    errs = consistency_check.check_ticket(ticket)
    assert errs == []
    assert provenance.check_artefacts(ticket) == []
