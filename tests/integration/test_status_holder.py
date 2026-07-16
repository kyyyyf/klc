#!/usr/bin/env python3
"""tests/integration/test_status_holder.py — KLC-060 step-3.

`klc status <ticket>` annotates the current-phase row with the holder id
(`· held by <id>`) and, when the phase is `ack-needed`, a
`· waiting on ack from <id>` hint. Holder-less and non-ack-needed renders must
not crash and must show no holder text. status is read-only: it must never
rewrite meta.json.

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


def _current_line(stdout: str) -> str:
    for line in stdout.splitlines():
        if "← now" in line:
            return line
    raise AssertionError(f"no current-phase row in:\n{stdout}")


def test_status_ack_needed_shows_waiting_hint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-SH-1", phase="design:ack-needed", track="M",
                   holder=_HOLDER)
        r = _run(["status", "T-SH-1"], root)
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        line = _current_line(r.stdout)
        assert "waiting on ack from alice" in line, line


def test_status_other_state_shows_holder_no_waiting() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-SH-2", phase="design:work", track="M", holder=_HOLDER)
        r = _run(["status", "T-SH-2"], root)
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        line = _current_line(r.stdout)
        assert "held by alice" in line, line
        assert "waiting on ack" not in line, line


def test_status_no_holder_no_crash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-SH-3", phase="design:ack-needed", track="M")
        r = _run(["status", "T-SH-3"], root)
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        line = _current_line(r.stdout)
        assert "held by" not in line, line
        assert "waiting on ack" not in line, line


def test_status_degraded_holder_no_crash() -> None:
    """Holder dict without an id fails closed: no text, no crash."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "T-SH-4", phase="design:ack-needed", track="M",
                   holder={"machine": "box"})
        r = _run(["status", "T-SH-4"], root)
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        line = _current_line(r.stdout)
        assert "held by" not in line and "waiting on ack" not in line, line


def test_status_does_not_write_meta() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        meta_p = _bootstrap(kd, "T-SH-5", phase="design:ack-needed", track="M",
                            holder=_HOLDER)
        before = meta_p.read_bytes()
        r = _run(["status", "T-SH-5"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert meta_p.read_bytes() == before, "status rewrote meta.json"


def test_status_does_not_write_meta_legacy_phase() -> None:
    """KLC-062 AC-2: a legacy-format phase string must NOT be persisted back to
    disk on a read-only `klc status`. The migration is applied in-memory (so the
    modern phase shows in the render), but meta.json stays byte-identical.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        # "design-pending" is a legacy phase → migrates to "design:work".
        meta_p = _bootstrap(kd, "T-SH-6", phase="design-pending", track="M",
                            holder=_HOLDER)
        before = meta_p.read_bytes()
        r = _run(["status", "T-SH-6"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        # In-memory migration still surfaces the modern phase in the render.
        line = _current_line(r.stdout)
        assert "design" in line, line
        # …but the read must not write the migration back.
        assert meta_p.read_bytes() == before, (
            "status persisted a legacy-phase migration (must be read-only)"
        )
