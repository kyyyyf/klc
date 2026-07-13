#!/usr/bin/env python3
"""tests/integration/test_board_holder.py — KLC-060 step-2.

`klc board` surfaces the current-phase holder id: `held by <id>` in the text
render and a `holder_id` key in `--json` (omitted entirely when absent).
Holder-less rows must stay byte-identical to today, and board is read-only —
it must never rewrite meta.json.

Subprocess harness mirrors tests/integration/test_retrack.py.
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


def _bootstrap(klc_dir: Path, ticket: str, *, phase: str, track: str,
               holder=None) -> Path:
    tdir = klc_dir / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "affected_modules": [], "estimate": None,
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if holder is not None:
        meta["holder"] = holder
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return tdir / "meta.json"


def _run(args: list[str], root: Path):
    return subprocess.run([sys.executable, str(KLC), *args],
                          capture_output=True, text=True, env=_env(root))


_HOLDER = {"id": "alice", "machine": "box", "since": "2026-01-01T00:00:00Z"}


def test_board_text_shows_holder_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-BH-1", phase="design:work", track="M", holder=_HOLDER)
        r = _run(["board"], root)
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        assert "T-BH-1" in r.stdout
        assert "held by alice" in r.stdout, r.stdout


def test_board_json_shows_holder_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-BH-2", phase="design:work", track="M", holder=_HOLDER)
        r = _run(["board", "--json"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        data = json.loads(r.stdout)
        rows = [rec for recs in data.values() for rec in recs]
        row = next(rec for rec in rows if rec["key"] == "T-BH-2")
        assert row["holder_id"] == "alice", row


def test_board_no_holder_unchanged() -> None:
    """Holder-less text row must be byte-identical to today (no trailing text)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-BH-3", phase="design:work", track="M")
        r = _run(["board"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "held by" not in r.stdout, r.stdout
        # exact row shape preserved
        assert "  T-BH-3  track=M   kind=tech" in r.stdout, repr(r.stdout)


def test_board_no_holder_no_key_error() -> None:
    """A degraded holder (dict without id) must not crash and shows no text."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-BH-4", phase="design:work", track="M",
                   holder={"machine": "box"})
        r = _run(["board"], root)
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        assert "held by" not in r.stdout, r.stdout


def test_board_json_no_holder_valid_json() -> None:
    """--json with no holder must omit holder_id and stay valid JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-BH-5", phase="design:work", track="M")
        r = _run(["board", "--json"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        data = json.loads(r.stdout)
        rows = [rec for recs in data.values() for rec in recs]
        row = next(rec for rec in rows if rec["key"] == "T-BH-5")
        assert "holder_id" not in row, row


def test_board_does_not_write_meta() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        meta_p = _bootstrap(kd, "T-BH-6", phase="design:work", track="M",
                            holder=_HOLDER)
        before = meta_p.read_bytes()
        r = _run(["board"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        _run(["board", "--json"], root)
        assert meta_p.read_bytes() == before, "board rewrote meta.json"
