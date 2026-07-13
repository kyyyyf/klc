#!/usr/bin/env python3
"""tests/test_holder_steal.py — heartbeat + steal for the holder primitive (KLC-058).

Builds on KLC-056's holder.py. Two new operations, both pure logic over
lifecycle.read_meta / lifecycle.write_meta (no direct fs/git IO):

  heartbeat_holder(ticket) — refresh holder.heartbeat_at to now (UTC Z),
    leaving every other holder field intact; ValueError when no holder.

  steal_holder(ticket, identity, ttl_seconds=...) — take over a holder slot
    ONLY when the current holder is stale (age from heartbeat_at, else since,
    older than the TTL). Within TTL → HolderActiveError. Expired → overwrite.

Skill-level tests patch read_meta/write_meta with an in-memory store. The
`klc steal` CLI + dispatch tests exercise the real phase on a temp .klc tree.

Run:  python -m pytest tests/test_holder_steal.py -v
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
            "ticket": "KLC-058", "phase": "build:work",
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


def _iso(dt: _dt.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ago(seconds: int) -> str:
    return _iso(_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=seconds))


def _assert_iso_utc_z(ts: str) -> None:
    assert isinstance(ts, str) and ts.endswith("Z"), f"must end in Z: {ts!r}"
    parsed = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


# ===========================================================================
# step-1 — heartbeat_holder (AC-2)
# ===========================================================================

def test_heartbeat_updates_only_heartbeat_at(store):
    store.data["holder"] = {
        "id": IDENT_A["id"], "machine": IDENT_A["machine"],
        "since": "2026-07-10T00:00:00Z",
    }
    result = holder.heartbeat_holder("KLC-058")
    # Every pre-existing field is preserved unchanged.
    assert store.data["holder"]["id"] == IDENT_A["id"]
    assert store.data["holder"]["machine"] == IDENT_A["machine"]
    assert store.data["holder"]["since"] == "2026-07-10T00:00:00Z"
    # heartbeat_at was added / refreshed.
    assert "heartbeat_at" in store.data["holder"]
    assert result["heartbeat_at"] == store.data["holder"]["heartbeat_at"]


def test_heartbeat_preserves_sibling_meta_keys(store):
    store.data = {
        "ticket": "KLC-058", "phase": "build:work",
        "phase_history": [{"phase": "build:work"}],
        "holder": {"id": IDENT_A["id"], "machine": IDENT_A["machine"],
                   "since": "2026-07-10T00:00:00Z"},
    }
    holder.heartbeat_holder("KLC-058")
    assert store.data["ticket"] == "KLC-058"
    assert store.data["phase"] == "build:work"
    assert store.data["phase_history"] == [{"phase": "build:work"}]


def test_heartbeat_refreshes_existing_heartbeat_at(store):
    store.data["holder"] = {
        "id": IDENT_A["id"], "machine": IDENT_A["machine"],
        "since": "2026-07-10T00:00:00Z",
        "heartbeat_at": "2026-07-10T00:05:00Z",
    }
    result = holder.heartbeat_holder("KLC-058")
    assert result["heartbeat_at"] != "2026-07-10T00:05:00Z"


def test_heartbeat_timestamp_is_iso_utc_z(store):
    store.data["holder"] = {
        "id": IDENT_A["id"], "machine": IDENT_A["machine"],
        "since": "2026-07-10T00:00:00Z",
    }
    result = holder.heartbeat_holder("KLC-058")
    _assert_iso_utc_z(result["heartbeat_at"])
    _assert_iso_utc_z(store.data["holder"]["heartbeat_at"])


def test_heartbeat_when_no_holder_raises_valueerror(store):
    assert "holder" not in store.data
    with pytest.raises(ValueError):
        holder.heartbeat_holder("KLC-058")


def test_heartbeat_when_null_holder_raises_valueerror(store):
    store.data["holder"] = None
    with pytest.raises(ValueError):
        holder.heartbeat_holder("KLC-058")
