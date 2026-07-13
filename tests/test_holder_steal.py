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


# ===========================================================================
# step-2 — steal_holder skill logic (AC-1)
# ===========================================================================

def test_steal_within_ttl_raises_and_leaves_holder(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(60),  # 1 min ago, well within the 30-min TTL
    }
    with pytest.raises(holder.HolderActiveError) as excinfo:
        holder.steal_holder("KLC-058", IDENT_A)
    err = excinfo.value
    # Typed error carries the current holder + measured age; message names id.
    assert err.holder["id"] == IDENT_B["id"]
    assert err.age_seconds is not None and err.age_seconds >= 0
    assert IDENT_B["id"] in str(err)
    # Holder untouched — no takeover.
    assert store.data["holder"]["id"] == IDENT_B["id"]


def test_steal_when_expired_overwrites_holder(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(60 * 60),  # 1 hour ago — past the 30-min TTL
    }
    result = holder.steal_holder("KLC-058", IDENT_A)
    # New holder is the stealer, written to the store.
    assert result["holder"]["id"] == IDENT_A["id"]
    assert result["holder"]["machine"] == IDENT_A["machine"]
    assert store.data["holder"]["id"] == IDENT_A["id"]
    # Result reports who was displaced and how stale they were.
    assert result["previous"]["id"] == IDENT_B["id"]
    assert result["age_seconds"] >= 60 * 60
    # New holder has a fresh ISO-8601 UTC `since`.
    _assert_iso_utc_z(store.data["holder"]["since"])


def test_steal_prefers_heartbeat_at_over_since(store):
    # `since` is ancient, but a recent heartbeat proves the holder is alive.
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(60 * 60),
        "heartbeat_at": _ago(30),
    }
    with pytest.raises(holder.HolderActiveError):
        holder.steal_holder("KLC-058", IDENT_A)
    assert store.data["holder"]["id"] == IDENT_B["id"]


def test_steal_uses_since_when_heartbeat_absent(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(60 * 60),  # no heartbeat_at → fall back to since
    }
    result = holder.steal_holder("KLC-058", IDENT_A)
    assert result["holder"]["id"] == IDENT_A["id"]


def test_steal_expired_via_stale_heartbeat(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(10),  # recently acquired ...
        "heartbeat_at": _ago(60 * 60),  # ... but heartbeat went stale
    }
    result = holder.steal_holder("KLC-058", IDENT_A)
    assert result["holder"]["id"] == IDENT_A["id"]


def test_steal_no_holder_raises_valueerror(store):
    assert "holder" not in store.data
    with pytest.raises(ValueError):
        holder.steal_holder("KLC-058", IDENT_A)


def test_steal_null_holder_raises_valueerror(store):
    store.data["holder"] = None
    with pytest.raises(ValueError):
        holder.steal_holder("KLC-058", IDENT_A)


def test_steal_invalid_identity_raises_valueerror(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60 * 60),
    }
    with pytest.raises(ValueError):
        holder.steal_holder("KLC-058", {"id": "no-machine"})


def test_steal_custom_ttl_override(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(120),  # 2 min ago
    }
    # Within the default 30-min TTL → active.
    with pytest.raises(holder.HolderActiveError):
        holder.steal_holder("KLC-058", IDENT_A)
    # With a 60-second TTL, 2 min is stale → stealable.
    result = holder.steal_holder("KLC-058", IDENT_A, ttl_seconds=60)
    assert result["holder"]["id"] == IDENT_A["id"]


def test_steal_calls_on_takeover_before_write(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60 * 60),
    }
    seen = {}

    def _cb(prev, age):
        # Warning fires BEFORE the store is overwritten (AC-1: warn before takeover).
        seen["prev_id"] = prev["id"]
        seen["age"] = age
        seen["holder_at_callback"] = store.data["holder"]["id"]

    holder.steal_holder("KLC-058", IDENT_A, on_takeover=_cb)
    assert seen["prev_id"] == IDENT_B["id"]
    assert seen["age"] >= 60 * 60
    # At callback time the old holder was still in place.
    assert seen["holder_at_callback"] == IDENT_B["id"]
    # After the call the takeover is committed.
    assert store.data["holder"]["id"] == IDENT_A["id"]


def test_steal_active_holder_does_not_call_on_takeover(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60),
    }
    calls = []
    with pytest.raises(holder.HolderActiveError):
        holder.steal_holder("KLC-058", IDENT_A, on_takeover=lambda p, a: calls.append(1))
    assert calls == []


def test_steal_ttl_default_is_30_minutes():
    assert holder.HOLDER_TTL_SECONDS == 30 * 60


# ===========================================================================
# step-2 — `klc steal <KEY>` CLI + dispatcher wiring (AC-1)
# ===========================================================================

import importlib.util  # noqa: E402
import json  # noqa: E402

STEAL_PY = FW_ROOT / "core" / "phases" / "steal.py"
KLC_SCRIPT = FW_ROOT / "scripts" / "klc"


def _load_steal():
    spec = importlib.util.spec_from_file_location("klc_phase_steal", STEAL_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_meta(root: Path, ticket: str, holder_rec: dict | None) -> Path:
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {"ticket": ticket, "phase": "build:work"}
    if holder_rec is not None:
        meta["holder"] = holder_rec
    p = tdir / "meta.json"
    p.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return p


def _read_holder(meta_path: Path) -> dict | None:
    return json.loads(meta_path.read_text(encoding="utf-8")).get("holder")


@pytest.fixture
def steal_env(tmp_path, monkeypatch):
    """Load steal.py against a temp PROJECT_ROOT with a fixed stealer identity."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mod = _load_steal()
    monkeypatch.setattr(mod._identity, "current", lambda: "carol@stealbox")
    monkeypatch.setattr(mod.socket, "gethostname", lambda: "stealbox")
    return mod, tmp_path


def test_steal_cli_within_ttl_fails_and_preserves_holder(steal_env, capsys):
    mod, root = steal_env
    meta_path = _write_meta(root, "KLC-058", {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60),
    })
    rc = mod.run(["KLC-058"])
    assert rc != 0
    err = capsys.readouterr().err
    assert IDENT_B["id"] in err  # names the current holder
    # Holder untouched.
    assert _read_holder(meta_path)["id"] == IDENT_B["id"]


def test_steal_cli_expired_succeeds_warns_and_overwrites(steal_env, capsys):
    mod, root = steal_env
    meta_path = _write_meta(root, "KLC-058", {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60 * 60),
    })
    rc = mod.run(["KLC-058"])
    assert rc == 0
    out = capsys.readouterr()
    # A warning was printed (before takeover); the old holder id is mentioned.
    combined = out.out + out.err
    assert "WARN" in combined.upper()
    assert IDENT_B["id"] in combined
    # Holder overwritten with the stealer's identity.
    assert _read_holder(meta_path)["id"] == "carol@stealbox"
    assert _read_holder(meta_path)["machine"] == "stealbox"


def test_steal_cli_unknown_ticket_fails(steal_env, capsys):
    mod, _root = steal_env
    rc = mod.run(["KLC-999"])
    assert rc != 0


def test_steal_dispatch_registered_in_klc(steal_env):
    """`klc steal` routes to core/phases/steal.py via the dispatcher."""
    text = KLC_SCRIPT.read_text(encoding="utf-8")
    assert '"steal"' in text or "'steal'" in text
    # And the phase entry point exists with a run() function.
    mod, _root = steal_env
    assert hasattr(mod, "run")


# ===========================================================================
# review-fix — L1: --ttl-minutes <= 0 must NOT steal a live holder
# ===========================================================================

def test_steal_cli_zero_ttl_rejected_holder_unchanged(steal_env, capsys):
    mod, root = steal_env
    meta_path = _write_meta(root, "KLC-058", {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60),
    })
    rc = mod.run(["KLC-058", "--ttl-minutes", "0"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "ttl" in err.lower() and "positive" in err.lower()
    # A ttl of 0 must not bypass the "refuse while alive" contract.
    assert _read_holder(meta_path)["id"] == IDENT_B["id"]


def test_steal_cli_negative_ttl_rejected_holder_unchanged(steal_env, capsys):
    mod, root = steal_env
    meta_path = _write_meta(root, "KLC-058", {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60),
    })
    rc = mod.run(["KLC-058", "--ttl-minutes", "-5"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "ttl" in err.lower() and "positive" in err.lower()
    assert _read_holder(meta_path)["id"] == IDENT_B["id"]


# ===========================================================================
# review-fix — L2/L5: malformed / non-string / future liveness timestamps
# ===========================================================================

def test_steal_nonstring_heartbeat_falls_back_to_since(store):
    # A non-string heartbeat_at must NOT crash; fall back to the stale `since`.
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(60 * 60),   # stale
        "heartbeat_at": 12345,     # garbage (int)
    }
    result = holder.steal_holder("KLC-058", IDENT_A)
    assert result["holder"]["id"] == IDENT_A["id"]


def test_steal_bool_heartbeat_falls_back_to_since(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(60 * 60),
        "heartbeat_at": True,      # garbage (bool)
    }
    result = holder.steal_holder("KLC-058", IDENT_A)
    assert result["holder"]["id"] == IDENT_A["id"]


def test_steal_malformed_string_heartbeat_falls_back_to_since(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(60 * 60),
        "heartbeat_at": "not-an-iso-timestamp",
    }
    result = holder.steal_holder("KLC-058", IDENT_A)
    assert result["holder"]["id"] == IDENT_A["id"]


def test_steal_both_timestamps_corrupt_raises_valueerror(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": "not-a-timestamp",
        "heartbeat_at": 99,
    }
    with pytest.raises(ValueError):
        holder.steal_holder("KLC-058", IDENT_A)


def test_steal_future_heartbeat_treated_as_active(store):
    # A future heartbeat proves (nominally) liveness → refuse to steal; safe.
    future = _iso(_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=10))
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": _ago(60 * 60),
        "heartbeat_at": future,
    }
    with pytest.raises(holder.HolderActiveError):
        holder.steal_holder("KLC-058", IDENT_A)
    assert store.data["holder"]["id"] == IDENT_B["id"]


def test_steal_cli_corrupt_timestamps_clean_error_not_traceback(steal_env, capsys):
    # Both liveness stamps corrupt → clean non-zero exit + message, no traceback.
    mod, root = steal_env
    meta_path = _write_meta(root, "KLC-058", {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"],
        "since": "not-iso", "heartbeat_at": 99,
    })
    rc = mod.run(["KLC-058"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "klc steal" in err  # a friendly message, not a bare traceback
    assert _read_holder(meta_path)["id"] == IDENT_B["id"]


# ===========================================================================
# review-fix — L4: printed output must be ASCII (C/ascii-locale safe)
# ===========================================================================

def test_steal_cli_takeover_output_is_ascii(steal_env, capsys):
    mod, root = steal_env
    _write_meta(root, "KLC-058", {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60 * 60),
    })
    rc = mod.run(["KLC-058"])
    assert rc == 0
    out = capsys.readouterr()
    # Warning (was '≥') + success line (was '→') must encode under ascii.
    (out.out + out.err).encode("ascii")


# ===========================================================================
# review-fix2 — P2: AC-2's documented interface lives on lifecycle.py too.
# `lifecycle.heartbeat_holder` / `lifecycle.steal_holder` must delegate to the
# real implementations in holder.py (no duplicated logic, no import cycle).
# ===========================================================================

def test_lifecycle_heartbeat_holder_is_callable():
    assert callable(lifecycle.heartbeat_holder)


def test_lifecycle_steal_holder_is_callable():
    assert callable(lifecycle.steal_holder)


def test_lifecycle_heartbeat_delegates_to_holder(store):
    store.data["holder"] = {
        "id": IDENT_A["id"], "machine": IDENT_A["machine"],
        "since": "2026-07-10T00:00:00Z",
    }
    result = lifecycle.heartbeat_holder("KLC-058")
    # Behaves identically to holder.heartbeat_holder: adds heartbeat_at,
    # preserves the other fields.
    assert store.data["holder"]["id"] == IDENT_A["id"]
    assert store.data["holder"]["since"] == "2026-07-10T00:00:00Z"
    _assert_iso_utc_z(store.data["holder"]["heartbeat_at"])
    assert result["heartbeat_at"] == store.data["holder"]["heartbeat_at"]


def test_lifecycle_heartbeat_no_holder_raises_valueerror(store):
    assert "holder" not in store.data
    with pytest.raises(ValueError):
        lifecycle.heartbeat_holder("KLC-058")


def test_lifecycle_steal_delegates_to_holder(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60 * 60),
    }
    result = lifecycle.steal_holder("KLC-058", IDENT_A)
    assert result["holder"]["id"] == IDENT_A["id"]
    assert store.data["holder"]["id"] == IDENT_A["id"]


def test_lifecycle_steal_within_ttl_raises_holder_active(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(60),
    }
    with pytest.raises(holder.HolderActiveError):
        lifecycle.steal_holder("KLC-058", IDENT_A)
    assert store.data["holder"]["id"] == IDENT_B["id"]


def test_lifecycle_steal_forwards_ttl_kwarg(store):
    store.data["holder"] = {
        "id": IDENT_B["id"], "machine": IDENT_B["machine"], "since": _ago(120),
    }
    # kwargs (ttl_seconds) must be forwarded to holder.steal_holder.
    result = lifecycle.steal_holder("KLC-058", IDENT_A, ttl_seconds=60)
    assert result["holder"]["id"] == IDENT_A["id"]
