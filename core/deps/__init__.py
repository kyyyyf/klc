"""core/deps — dependency checking modules for klc framework.

Provides utilities for checking tool presence (bootstrap, dev, project modes).
Shared by bootstrap.py, dev.py, project.py.
"""
from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

# --- logging ------------------------------------------------------------------

_LOG_PATH: Path | None = None


def log_init(log_path: Path) -> None:
    """Initialize logging to the given path."""
    global _LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _LOG_PATH = log_path


def log(msg: str) -> None:
    """Log info message to stdout and log file."""
    line = f"[install-deps] {msg}"
    print(line)
    if _LOG_PATH:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def warn(msg: str) -> None:
    """Log warning message to stderr and log file."""
    line = f"[install-deps][warn] {msg}"
    sys.stderr.write(line + "\n")
    if _LOG_PATH:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def err(msg: str) -> None:
    """Log error message to stderr and log file."""
    line = f"[install-deps][err]  {msg}"
    sys.stderr.write(line + "\n")
    if _LOG_PATH:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


# --- platform ----------------------------------------------------------------


def platform_tag() -> str:
    """Return normalized platform tag (linux, macos, windows, unknown)."""
    s = platform.system()
    if s == "Linux":
        return "linux"
    if s == "Darwin":
        return "macos"
    if s == "Windows":
        return "windows"
    return "unknown"


# --- Tool checks -------------------------------------------------------------


def _has(name: str) -> Path | None:
    """Check if a tool is on PATH. Returns path if found, None otherwise."""
    hit = shutil.which(name)
    return Path(hit) if hit else None


def _check(
    missing: list[str],
    suggestions: list[str],
    *,
    name: str,
    hint: str,
    alt_names: tuple[str, ...] = (),
) -> bool:
    """Check for `name` (or any of alt_names) on PATH. Returns True if found.

    Appends to `missing` and `suggestions` lists if not found.
    """
    for n in (name, *alt_names):
        hit = _has(n)
        if hit:
            log(f"  ok  {name} ({hit})")
            return True
    missing.append(name)
    suggestions.append(f"{name}: {hint}")
    warn(f"  missing  {name}")
    return False


def _check_python_lib(
    missing: list[str], suggestions: list[str], *, module: str, install_hint: str
) -> bool:
    """Check if a Python module can be imported. Returns True if found.

    Appends to `missing` and `suggestions` lists if not found.
    """
    try:
        __import__(module)
        log(f"  ok  python module {module}")
        return True
    except ImportError:
        missing.append(module)
        suggestions.append(f"{module}: {install_hint}")
        warn(f"  missing  python module {module}")
        return False
