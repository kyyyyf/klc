#!/usr/bin/env python3
"""tests/integration/test_holder_display.py — KLC-060 step-1.

Unit coverage for the shared holder-display helper (`core/skills/holder_display.py`),
which formats the current-phase holder id and the "waiting on ack from <id>" hint
from a meta dict. Every degraded shape (no holder, holder without id, null id,
empty id) must fail closed — return None, never raise.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import holder_display  # noqa: E402


def _meta(holder):
    return {"ticket": "KLC-060", "phase": "design:ack-needed", "holder": holder}


# ---------------------------------------------------------------------------
# holder_label
# ---------------------------------------------------------------------------

def test_holder_label_present() -> None:
    m = _meta({"id": "alice", "machine": "box", "since": "2026-01-01T00:00:00Z"})
    assert holder_display.holder_label(m) == "alice"


def test_holder_label_missing_holder_key() -> None:
    assert holder_display.holder_label({"ticket": "KLC-060"}) is None


def test_holder_label_holder_null() -> None:
    assert holder_display.holder_label(_meta(None)) is None


def test_holder_label_holder_not_dict() -> None:
    assert holder_display.holder_label(_meta("alice")) is None


def test_holder_label_missing_id() -> None:
    assert holder_display.holder_label(_meta({"machine": "box"})) is None


def test_holder_label_id_null() -> None:
    assert holder_display.holder_label(_meta({"id": None, "machine": "box"})) is None


def test_holder_label_id_empty() -> None:
    assert holder_display.holder_label(_meta({"id": "", "machine": "box"})) is None


def test_holder_label_id_whitespace() -> None:
    assert holder_display.holder_label(_meta({"id": "   ", "machine": "box"})) is None


def test_holder_label_none_meta() -> None:
    assert holder_display.holder_label(None) is None


# ---------------------------------------------------------------------------
# waiting_hint — only in ack-needed AND with a valid holder id
# ---------------------------------------------------------------------------

def test_waiting_hint_ack_needed_with_id() -> None:
    m = _meta({"id": "alice", "machine": "box", "since": "2026-01-01T00:00:00Z"})
    assert holder_display.waiting_hint(m, "ack-needed") == "waiting on ack from alice"


def test_waiting_hint_work_state_none() -> None:
    m = _meta({"id": "alice", "machine": "box", "since": "2026-01-01T00:00:00Z"})
    assert holder_display.waiting_hint(m, "work") is None


def test_waiting_hint_ack_state_none() -> None:
    m = _meta({"id": "alice", "machine": "box", "since": "2026-01-01T00:00:00Z"})
    assert holder_display.waiting_hint(m, "ack") is None


def test_waiting_hint_ack_needed_no_holder() -> None:
    assert holder_display.waiting_hint(_meta(None), "ack-needed") is None


def test_waiting_hint_ack_needed_empty_id() -> None:
    assert holder_display.waiting_hint(_meta({"id": "", "machine": "box"}), "ack-needed") is None
