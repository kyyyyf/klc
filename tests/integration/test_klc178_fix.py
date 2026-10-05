#!/usr/bin/env python3
"""KLC-178 step-1 — `klc fix <KEY> <field> <value...> --reason TEXT`.

AC-1: six fields append {field, before, after, reason, at, by} to meta.fixes[];
      --dry-run prints the record and leaves meta.json byte-identical.
AC-2: `track` keeps retrack semantics (refusals exit 1, phase_history event,
      track_source=operator).
AC-3: `modules` --add/--remove/--set works in any state, vocabulary migration reachable.
AC-4: bad input exits 2 and leaves meta.json byte-identical.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parents[2]
KLC = FW / "scripts" / "klc"
RECORD_KEYS = {"field", "before", "after", "reason", "at", "by"}


def _klc(argv, root: Path):
    env = {**os.environ, "PROJECT_ROOT": str(root)}
    env.pop("KLC_TICKETS_DIR", None)
    p = subprocess.run([sys.executable, str(KLC), *argv], capture_output=True,
                       text=True, env=env)
    return p.returncode, p.stdout, p.stderr


def _ticket(root: Path, key: str, phase: str = "discovery:work", track: str = "L",
            **extra) -> Path:
    td = root / ".klc" / "tickets" / key
    td.mkdir(parents=True)
    meta = {"ticket": key, "kind": "tech", "phase": phase, "track": track,
            "phase_history": [], "affected_modules": ["a", "b"],
            "created": "2026-01-01T00:00:00Z", **extra}
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return td / "meta.json"


FIELD_CASES = [
    ("track", ["M"], "track", "L", "M"),
    ("modules", ["--add", "c"], "affected_modules", ["a", "b"], ["a", "b", "c"]),
    ("risk-tags", ["data,security"], "risk_tags", None, ["data", "security"]),
    ("kind", ["bug"], "kind", "tech", "bug"),
    ("epic", ["KLC-100"], "epic", None, "KLC-100"),
    ("blocked-by", ["KLC-077@integrated#build"], "blocked_by", None, None),
]


@pytest.mark.parametrize("field,value,key,before,after", FIELD_CASES)
def test_each_field_records_before_after_and_dry_run_writes_nothing(
        tmp_path, field, value, key, before, after):
    mp = _ticket(tmp_path, "T-FX-1")
    raw = mp.read_bytes()

    rc, out, err = _klc(["fix", "T-FX-1", field, *value, "--reason", "r1", "--dry-run",
                         "--json"], tmp_path)
    assert rc == 0, err
    dry = json.loads(out)
    assert RECORD_KEYS <= set(dry) and dry["field"] == field and dry["reason"] == "r1"
    assert mp.read_bytes() == raw, "dry-run must not write"

    rc, out, err = _klc(["fix", "T-FX-1", field, *value, "--reason", "r1", "--json"],
                        tmp_path)
    assert rc == 0, err
    rec = json.loads(out)
    assert RECORD_KEYS <= set(rec) and rec["by"] and rec["at"]
    meta = json.loads(mp.read_text())
    assert meta["fixes"] == [rec]
    assert rec["before"] == (before if before is not None else rec["before"])
    if after is not None:
        assert meta[key] == after and rec["after"] == after
    else:
        assert meta[key] and rec["after"] == meta[key]
        assert meta[key][0]["on"] == "KLC-077"


def test_clear_epic_and_blocked_by_with_dash(tmp_path):
    mp = _ticket(tmp_path, "T-FX-2", epic="KLC-100",
                 blocked_by=[{"on": "KLC-077", "point": "integrated", "phase": "build"}])
    for field in ("epic", "blocked-by"):
        rc, _, err = _klc(["fix", "T-FX-2", field, "-", "--reason", "clear"], tmp_path)
        assert rc == 0, err
    meta = json.loads(mp.read_text())
    assert not meta.get("epic") and not meta.get("blocked_by")
    assert [f["field"] for f in meta["fixes"]] == ["epic", "blocked-by"]


def test_track_keeps_retrack_semantics_and_refuses_incompatible_phase(tmp_path):
    mp = _ticket(tmp_path, "T-FX-3", phase="intake:ack-needed", track="L")
    rc, _, err = _klc(["fix", "T-FX-3", "track", "S", "--reason", "small"], tmp_path)
    assert rc == 0, err
    meta = json.loads(mp.read_text())
    assert meta["track"] == "S" and meta["track_source"] == "operator"
    ev = [h for h in meta["phase_history"] if h.get("event") == "retrack"]
    assert ev and ev[0]["from_track"] == "L" and ev[0]["to_track"] == "S"
    assert meta["fixes"][0]["before"] == "L" and meta["fixes"][0]["after"] == "S"

    done = _ticket(tmp_path, "T-FX-4", phase="archived", track="L")
    raw = done.read_bytes()
    rc, _, _ = _klc(["fix", "T-FX-4", "track", "S", "--reason", "x"], tmp_path)
    assert rc == 1 and done.read_bytes() == raw

    # KLC-179: a phase the other lane lacks no longer blocks the move. The facts stay and the
    # ticket lands on the first missing fact of the light lane (never on archived).
    from_pid = _ticket(tmp_path, "T-FX-5", phase="design:work", track="L")
    rc, _, _ = _klc(["fix", "T-FX-5", "track", "XS", "--reason", "x"], tmp_path)
    assert rc == 0
    meta = json.loads(from_pid.read_text())
    assert meta["track"] == "XS" and meta["facts"]["track"] == "light"
    assert meta["phase"] == "discovery-lite:work"


@pytest.mark.parametrize("phase", ["integrate:ack-needed", "archived"])
def test_modules_works_on_merged_and_archived_tickets(tmp_path, phase):
    mp = _ticket(tmp_path, "T-FX-6", phase=phase)
    rc, _, err = _klc(["fix", "T-FX-6", "modules", "--remove", "a", "--reason", "r"],
                      tmp_path)
    assert rc == 0, err
    assert json.loads(mp.read_text())["affected_modules"] == ["b"]
    rc, _, err = _klc(["fix", "T-FX-6", "modules", "--set", "x,y", "--reason", "r"],
                      tmp_path)
    assert rc == 0, err
    assert json.loads(mp.read_text())["affected_modules"] == ["x", "y"]
    assert len(json.loads(mp.read_text())["fixes"]) == 2
    rc, out, err = _klc(["fix", "--migrate-vocabulary", "--dry-run", "--json"], tmp_path)
    assert rc == 0, err
    json.loads(out)


@pytest.mark.parametrize("argv", [
    ["T-FX-7", "bogus", "x", "--reason", "r"],
    ["T-FX-7", "kind", "bug"],
    ["T-FX-7", "kind", "bug", "--reason", "  "],
    ["T-FX-7", "modules", "--add", "a,,b", "--reason", "r"],
    ["T-FX-7", "modules", "--reason", "r"],
    ["T-NOPE", "kind", "bug", "--reason", "r"],
    ["T-FX-7", "kind", "epic-sized", "--reason", "r"],
    ["T-FX-7", "track", "XL", "--reason", "r"],
    ["T-FX-7", "blocked-by", "garbage", "--reason", "r"],
    ["T-FX-7", "risk-tags", "a,,b", "--reason", "r"],
])
def test_bad_input_exits_nonzero_and_leaves_meta_untouched(tmp_path, argv):
    mp = _ticket(tmp_path, "T-FX-7")
    raw = mp.read_bytes()
    rc, _, err = _klc(["fix", *argv], tmp_path)
    assert rc == 2, (rc, err)
    assert err.strip()
    assert mp.read_bytes() == raw


def test_same_track_is_a_noop_exit_zero_like_other_fields(tmp_path):
    """F-007: `fix track` to the value the ticket already has is a no-op, exit 0."""
    mp = _ticket(tmp_path, "T-FX-8", phase="integrate:ack-needed", track="S")
    raw = mp.read_bytes()
    rc, out, err = _klc(["fix", "T-FX-8", "track", "S", "--reason", "r"], tmp_path)
    assert rc == 0, err
    assert "nothing to change" in out and mp.read_bytes() == raw
    rc, out, err = _klc(["fix", "T-FX-8", "kind", "tech", "--reason", "r"], tmp_path)
    assert rc == 0 and mp.read_bytes() == raw


def test_epic_refuses_the_tickets_own_key(tmp_path):
    """F-008: a ticket cannot be its own epic."""
    mp = _ticket(tmp_path, "T-FX-9")
    raw = mp.read_bytes()
    rc, _, err = _klc(["fix", "T-FX-9", "epic", "T-FX-9", "--reason", "r"], tmp_path)
    assert rc == 2 and err.strip() and mp.read_bytes() == raw


@pytest.mark.parametrize("bad", ["not-a-key", "klc-1", "KLC_1", "1-KLC"])
def test_epic_validates_the_key_shape(tmp_path, bad):
    """R2-003: fix epic accepts only a ticket-key-shaped token (or `-`)."""
    mp = _ticket(tmp_path, "T-FX-8")
    raw = mp.read_bytes()
    rc, _, err = _klc(["fix", "T-FX-8", "epic", bad, "--reason", "r"], tmp_path)
    assert rc == 2 and err.strip() and mp.read_bytes() == raw
