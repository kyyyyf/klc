#!/usr/bin/env python3
"""store_lock.py — a tiny advisory lock and atomic write for the two per-ticket
stores, `findings.json` and `advisories.json` (KLC-173 review round 1, F-013).

Both stores are read-modify-write, and a headless `review.py` run can pool
partials while an in-client `take` stores a verdict. The lock file lives in the
system temporary directory (keyed by the store's path), never next to the
store, so a clean ticket directory stays free of `.lock` files. On Windows, or
when the lock cannot be taken, the code runs unlocked: the lock is a courtesy,
never a reason to fail an ack.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from pathlib import Path

try:
    import fcntl
except ImportError:                                    # Windows: no lock
    fcntl = None


@contextlib.contextmanager
def locked(store_path):
    fd = None
    if fcntl is not None:
        try:
            key = hashlib.sha256(str(Path(store_path).resolve()).encode("utf-8")).hexdigest()[:24]
            lock_dir = Path(tempfile.gettempdir()) / "klc-locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock_dir / f"{key}.lock", os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            if fd is not None:
                os.close(fd)
            fd = None
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)                               # closing releases the flock


def atomic_write_text(p, text: str) -> None:
    """Write *text* to *p* through a per-process unique temp file in the same
    directory, then `os.replace`. Raises OSError; never leaves a temp file."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)                  # mkstemp makes 0600; keep the default mode
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
