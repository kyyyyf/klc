#!/usr/bin/env python3
"""tests/test_holder.py — unit tests for holder.py (KLC-056).

Pure-logic ownership primitive: acquire_holder / release_holder operate on a
`holder` sub-object in meta.json via lifecycle.read_meta / write_meta only.
Tests patch those two functions with an in-memory dict store — no real
filesystem or git access.

Run:  python -m pytest tests/test_holder.py -v
"""
from __future__ import annotations

import copy
import datetime as _dt
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import holder  # noqa: E402
import lifecycle  # noqa: E402


# ---------------------------------------------------------------------------
# in-memory meta store — replaces lifecycle.read_meta / write_meta
# ---------------------------------------------------------------------------

class MetaStore:
    """Holds one ticket's meta in memory; deep-copies on read/write so the
    functions under test cannot mutate our record except via write_meta."""

    def __init__(self, initial: dict | None = None):
        self.data = initial if initial is not None else {
            "ticket": "KLC-056", "phase": "build:work",
        }

    def read(self, ticket: str) -> dict:
        return copy.deepcopy(self.data)

    def write(self, ticket: str, meta: dict) -> None:
        self.data = copy.deepcopy(meta)


@pytest.fixture
def store(monkeypatch):
    s = MetaStore()
    monkeypatch.setattr(lifecycle, "read_meta", s.read)
    monkeypatch.setattr(lifecycle, "write_meta", s.write)
    return s


IDENT_A = {"id": "alice@host1", "machine": "host1"}
IDENT_B = {"id": "bob@host2", "machine": "host2"}


def _assert_iso_utc_z(ts: str) -> None:
    assert isinstance(ts, str) and ts.endswith("Z"), f"since must end in Z: {ts!r}"
    # Must parse as ISO-8601 (swap trailing Z for +00:00 for fromisoformat).
    parsed = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# AC-1 — acquire when holder absent/null
# ---------------------------------------------------------------------------

def test_ac1_acquire_when_absent_writes_and_returns(store):
    assert "holder" not in store.data
    result = holder.acquire_holder("KLC-056", IDENT_A)
    assert result["id"] == IDENT_A["id"]
    assert result["machine"] == IDENT_A["machine"]
    # Persisted to the store via write_meta.
    assert store.data["holder"]["id"] == IDENT_A["id"]
    assert store.data["holder"]["machine"] == IDENT_A["machine"]


def test_ac1_acquire_when_null_writes_and_returns(store):
    store.data["holder"] = None
    result = holder.acquire_holder("KLC-056", IDENT_A)
    assert result["id"] == IDENT_A["id"]
    assert store.data["holder"]["id"] == IDENT_A["id"]


# ---------------------------------------------------------------------------
# AC-2 — conflict when a DIFFERENT identity already holds
# ---------------------------------------------------------------------------

def test_ac2_conflict_when_different_holder(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": "2026-07-10T00:00:00Z",
    }
    with pytest.raises(holder.HolderConflictError) as excinfo:
        holder.acquire_holder("KLC-056", IDENT_A)
    err = excinfo.value
    # Carries the existing holder's id and since.
    assert err.holder["id"] == IDENT_B["id"]
    assert err.holder["since"] == "2026-07-10T00:00:00Z"
    # Holder left unchanged.
    assert store.data["holder"]["id"] == IDENT_B["id"]


# ---------------------------------------------------------------------------
# AC-3 — idempotent: same id re-acquires, `since` NOT overwritten
# ---------------------------------------------------------------------------

def test_ac3_idempotent_same_id_preserves_since(store):
    original_since = "2026-07-10T12:34:56Z"
    store.data["holder"] = {
        "id": IDENT_A["id"], "machine": IDENT_A["machine"],
        "since": original_since,
    }
    result = holder.acquire_holder("KLC-056", IDENT_A)
    assert result["id"] == IDENT_A["id"]
    # `since` must be preserved, not refreshed.
    assert result["since"] == original_since
    assert store.data["holder"]["since"] == original_since


# ---------------------------------------------------------------------------
# AC-8 — identity shape validation + since is ISO-8601 UTC Z
# ---------------------------------------------------------------------------

def test_ac8_since_is_iso_utc_z(store):
    result = holder.acquire_holder("KLC-056", IDENT_A)
    _assert_iso_utc_z(result["since"])
    _assert_iso_utc_z(store.data["holder"]["since"])


def test_ac8_missing_id_raises_valueerror(store):
    with pytest.raises(ValueError):
        holder.acquire_holder("KLC-056", {"machine": "host1"})


def test_ac8_empty_id_raises_valueerror(store):
    with pytest.raises(ValueError):
        holder.acquire_holder("KLC-056", {"id": "", "machine": "host1"})


def test_ac8_missing_machine_raises_valueerror(store):
    with pytest.raises(ValueError):
        holder.acquire_holder("KLC-056", {"id": "alice@host1"})


def test_ac8_empty_machine_raises_valueerror(store):
    with pytest.raises(ValueError):
        holder.acquire_holder("KLC-056", {"id": "alice@host1", "machine": ""})
