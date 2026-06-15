#!/usr/bin/env python3
"""Tests for `klc retrack <KEY> <track> --reason "..."` — sanctioned track change.

Covers the gap left by KLC-018: the route heuristic is downgrade-forbidden and
there is no verb to correct an over-routed track. retrack is the operator-only,
audited mechanism that allows changing the track in both directions.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
KLC = FW_ROOT / "scripts" / "klc"


def _env(root: Path) -> dict[str, str]:
    e = {**os.environ, "PROJECT_ROOT": str(root)}
    e.pop("KLC_TICKETS_DIR", None)
    return e


def _bootstrap(klc_dir: Path, ticket: str, *, phase: str, track: str) -> Path:
    tdir = klc_dir / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "affected_modules": [], "estimate": None,
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return tdir / "meta.json"


def _run(args: list[str], root: Path):
    return subprocess.run([sys.executable, str(KLC), *args],
                          capture_output=True, text=True, env=_env(root))


def test_retrack_changes_track() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        meta_p = _bootstrap(kd, "T-RT-1", phase="discovery:work", track="L")
        r = _run(["retrack", "T-RT-1", "M", "--reason", "over-routed by length"], root)
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        meta = json.loads(meta_p.read_text())
        assert meta["track"] == "M", f"track not changed: {meta['track']}"


def test_retrack_allows_downgrade() -> None:
    """The core gap: L -> S downgrade must be permitted."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        # at intake (present in every track) so the target track is compatible
        meta_p = _bootstrap(kd, "T-RT-2", phase="intake:ack-needed", track="L")
        r = _run(["retrack", "T-RT-2", "S", "--reason", "verbose desc, small fix"], root)
        assert r.returncode == 0, f"downgrade refused: {r.stderr}"
        assert json.loads(meta_p.read_text())["track"] == "S"


def test_retrack_requires_reason() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-RT-3", phase="intake:ack-needed", track="L")
        r = _run(["retrack", "T-RT-3", "M"], root)
        assert r.returncode != 0, "retrack without --reason must fail"


def test_retrack_records_audit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        meta_p = _bootstrap(kd, "T-RT-4", phase="intake:ack-needed", track="L")
        _run(["retrack", "T-RT-4", "S", "--reason", "audit me"], root)
        meta = json.loads(meta_p.read_text())
        hist = json.dumps(meta)
        assert "audit me" in hist, "reason not recorded"
        assert "retrack" in hist, "retrack event not recorded in history"
        # old track must be preserved somewhere in the audit entry
        events = [e for e in meta.get("phase_history", [])
                  if e.get("event") == "retrack"]
        assert events, "no retrack event in phase_history"
        ev = events[-1]
        assert ev.get("from_track") == "L" and ev.get("to_track") == "S"


def test_retrack_refuses_incompatible_phase() -> None:
    """Cannot retrack to a track whose phase set excludes the current phase."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        # discovery exists only on M/L; retracking to XS (no discovery) must refuse
        meta_p = _bootstrap(kd, "T-RT-5", phase="discovery:work", track="L")
        r = _run(["retrack", "T-RT-5", "XS", "--reason", "should refuse"], root)
        assert r.returncode != 0, "must refuse incompatible track"
        assert json.loads(meta_p.read_text())["track"] == "L", "track must be unchanged on refusal"


def test_retrack_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-RT-6", phase="intake:ack-needed", track="L")
        r = _run(["retrack", "T-RT-6", "M", "--reason", "x", "--json"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        data = json.loads(r.stdout)
        assert data.get("track") == "M" and data.get("ticket") == "T-RT-6"
