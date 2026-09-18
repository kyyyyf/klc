#!/usr/bin/env python3
"""index_lock.py — KLC-107 D-201: one writer at a time for `.klc/index/`.

Every process that writes `.klc/index/` — `scripts/update.py`,
`scripts/init.py --finalize` and the verb-side refresh (`index_refresh.py`)
— holds this lock while it writes, so a direct `klc update` and a
verb-triggered refresh can never interleave their writes into the same
artifacts (finding F-1).

Built on an atomic `os.open(path, O_CREAT | O_EXCL | O_WRONLY)` writing a
``{"pid", "at"}`` record, mirroring the record shape and the PID-liveness
reclaim of ``artefacts.acquire_lock`` (``core/skills/artefacts.py:63-99``) so
the codebase keeps one locking idiom. Neither `fcntl` nor `msvcrt` is used:
`O_EXCL` creation is atomic on POSIX and Windows alike and needs no
`os.name` branch (D-201).
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

ENV_HELD = "KLC_INDEX_LOCK_HELD"
MAX_LOCK_AGE_S = 900.0        # > the largest builder timeout in update.py (600s)


class IndexBusy(RuntimeError):
    """Raised when the lock is held by a live process and the wait expires."""

    def __init__(self, pid: int, age_s: float):
        super().__init__(f"index lock held by PID {pid} for {age_s:.1f}s")
        self.pid = pid
        self.age_s = age_s


def _pid_status(pid: int) -> str:
    """``"alive"`` (verified running), ``"dead"`` (confirmed gone/invalid), or
    ``"unknown"`` (e.g. a PermissionError from ``os.kill`` — the PID exists
    but liveness cannot be proven either way).

    The distinction matters for the age-based reclaim below: a VERIFIED-alive
    holder must never be reclaimed on age alone (review MEDIUM finding — the
    true sequential worst case across update.py's builders can exceed
    MAX_LOCK_AGE_S), while an unknown-liveness lock must still eventually be
    reclaimable, same as a confirmed-dead one."""
    if not pid:
        return "dead"
    try:
        os.kill(pid, 0)
        return "alive"
    except ProcessLookupError:
        return "dead"
    except ValueError:
        return "dead"
    except OSError:
        # PermissionError etc — the PID exists but we can't signal it.
        return "unknown"


def _pid_alive(pid: int) -> bool:
    """Back-compat convenience: True unless the PID is CONFIRMED dead/invalid."""
    return _pid_status(pid) != "dead"


def _read_record(lp: Path) -> tuple[int, float]:
    try:
        rec = json.loads(lp.read_text(encoding="utf-8"))
        pid = int(rec.get("pid", 0))
        at = float(rec.get("at", 0.0))
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return 0, 0.0
    return pid, max(0.0, time.time() - at)


def _try_create(lp: Path) -> None:
    """Atomic on POSIX and Windows alike — no fcntl/msvcrt branch (D-201)."""
    fd = os.open(str(lp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "at": time.time()}, fh)


def _reclaim(lp: Path, pid: int, age: float) -> None:
    try:
        lp.unlink()
    except OSError:
        pass


@contextlib.contextmanager
def acquire_index_lock(index_dir: Path, *, wait_s: float = 0.0, poll_s: float = 0.05):
    """Context manager. Yields the lock file path (or ``None`` when a live
    ancestor already holds it re-entrantly). Raises :class:`IndexBusy` when
    the lock is held by another live, non-stale process and ``wait_s``
    expires before it is released."""
    if os.environ.get(ENV_HELD) == "1":
        # An ancestor already owns it; never re-acquire (keeps a verb's
        # refresh from deadlocking against its own update.py child).
        yield None
        return
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    lp = index_dir / ".lock"
    deadline = time.monotonic() + max(0.0, wait_s)
    while True:
        try:
            _try_create(lp)
            break
        except FileExistsError:
            pid, age = _read_record(lp)
            status = _pid_status(pid)
            # A verified-alive holder is NEVER reclaimed on age alone — the
            # age ceiling applies only when the PID is dead or its liveness
            # cannot be proven (review MEDIUM finding).
            if status == "dead" or (status == "unknown" and age > MAX_LOCK_AGE_S):
                _reclaim(lp, pid, age)
                continue
            if time.monotonic() >= deadline:
                raise IndexBusy(pid, age)
            time.sleep(poll_s)
    try:
        yield lp
    finally:
        try:
            lp.unlink()
        except OSError:
            pass
