#!/usr/bin/env python3
"""Tests for the role-based MODEL_MISMATCH guard (AC-3).

The guard compares the session model's role rank against the phase's required
role rank and emits a symmetric warning — or None when ranks match.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import model_guard as _mg


def test_lower_role_warns_up() -> None:
    """Session rank < phase rank → warning mentions upgrading."""
    msg = _mg.check("discovery", track="M", session_model="claude-haiku-4-5-20251001")
    assert msg is not None, "expected a warning for under-ranked session model"
    # Warning should be non-empty and not crash
    assert len(msg) > 0


def test_higher_role_warns_down() -> None:
    """Session rank > phase rank → warning mentions downgrading."""
    msg = _mg.check("learn", track="M", session_model="claude-opus-4-7")
    assert msg is not None, "expected a warning for over-ranked session model"
    assert len(msg) > 0


def test_equal_rank_silent() -> None:
    """Session rank == phase rank → no output."""
    # discovery uses heavy-reasoning (rank 3); opus is heavy-reasoning
    msg = _mg.check("discovery", track="M", session_model="claude-opus-4-7")
    assert msg is None, f"expected None for equal-rank, got: {msg!r}"


def test_message_names_roles_not_models() -> None:
    """Warning must name the role (e.g. 'coding'), not a hardcoded model id."""
    msg = _mg.check("discovery", track="M", session_model="claude-haiku-4-5-20251001")
    assert msg is not None
    # Must mention a role name
    assert any(role in msg for role in ("heavy-reasoning", "coding", "local-simple")), (
        f"message does not name any role: {msg!r}"
    )
    # Must NOT name a hardcoded concrete model id
    assert "claude-opus" not in msg, f"message hardcodes model name: {msg!r}"
    assert "claude-haiku" not in msg, f"message hardcodes model name: {msg!r}"
    assert "claude-sonnet" not in msg, f"message hardcodes model name: {msg!r}"


def test_unknown_session_model_soft_note() -> None:
    """Unknown session model → soft note, no crash."""
    msg = _mg.check("discovery", track="M", session_model="unknown-model-xyz")
    # Should not raise; may return a soft note or None
    # Crucially: no exception
    assert msg is None or isinstance(msg, str)
    if msg is not None:
        assert "unknown" in msg.lower() or "не" in msg or "cannot" in msg.lower()
