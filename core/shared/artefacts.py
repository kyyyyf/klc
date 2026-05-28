"""Artefact writing and locking utilities for klc framework.

Provides:
- write_with_frontmatter(): Write markdown file with YAML frontmatter
- acquire_lock(): Context manager for per-ticket locking

Extracted from core/skills/artefacts.py and duplicated patterns (KLC-007).
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any


class LockedError(RuntimeError):
    """Raised when ticket is locked by another process."""
    pass


def _now() -> str:
    """Current UTC timestamp in ISO format."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_with_frontmatter(
    path: Path | str,
    frontmatter: dict[str, Any],
    content: str,
    *,
    encoding: str = "utf-8"
) -> None:
    """Write markdown file with YAML frontmatter.

    Args:
        path: Output file path
        frontmatter: Dict to serialize as YAML frontmatter
        content: Markdown content (after frontmatter)
        encoding: File encoding (default: utf-8)

    Output format:
        ---
        key: value
        nested:
          key: value
        ---

        Content starts here...

    Example:
        >>> write_with_frontmatter(
        ...     "spec.md",
        ...     {"ticket": "KLC-007", "authority": "agent"},
        ...     "# Spec\\n\\nContent..."
        ... )
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Serialize frontmatter as simple YAML (no external deps)
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(_serialize_yaml_value(key, value, indent=0))
    lines.append("---")
    lines.append("")  # blank line after frontmatter
    lines.append(content)

    path.write_text("\n".join(lines), encoding=encoding)


def _serialize_yaml_value(key: str, value: Any, indent: int) -> str:
    """Serialize single YAML key-value pair.

    Handles: str, int, bool, None, dict, list (flat only).
    """
    prefix = "  " * indent

    if value is None:
        return f"{prefix}{key}: null"
    elif isinstance(value, bool):
        return f"{prefix}{key}: {str(value).lower()}"
    elif isinstance(value, (int, float)):
        return f"{prefix}{key}: {value}"
    elif isinstance(value, str):
        # Quote if contains special chars
        if any(c in value for c in [":", "#", "[", "]", "{", "}"]):
            escaped = value.replace('"', '\\"')
            return f'{prefix}{key}: "{escaped}"'
        return f"{prefix}{key}: {value}"
    elif isinstance(value, list):
        if not value:
            return f"{prefix}{key}: []"
        # Simple list (flat items only)
        items = ", ".join(_format_list_item(v) for v in value)
        return f"{prefix}{key}: [{items}]"
    elif isinstance(value, dict):
        # Nested dict
        lines = [f"{prefix}{key}:"]
        for k, v in value.items():
            lines.append(_serialize_yaml_value(k, v, indent + 1))
        return "\n".join(lines)
    else:
        # Fallback: stringify
        return f"{prefix}{key}: {str(value)}"


def _format_list_item(item: Any) -> str:
    """Format single list item for inline YAML."""
    if isinstance(item, str):
        if any(c in item for c in [",", ":", "[", "]"]):
            return f'"{item}"'
        return item
    elif isinstance(item, bool):
        return str(item).lower()
    elif item is None:
        return "null"
    else:
        return str(item)


# --- Locking ------------------------------------------------------------------

def _lock_path(ticket: str) -> Path:
    """Path to lock file for ticket."""
    from core.shared.paths import klc_ticket_dir
    return klc_ticket_dir(ticket) / ".lock"


def _pid_alive(pid: int) -> bool:
    """Check if process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


@contextlib.contextmanager
def acquire_lock(ticket: str):
    """Acquire per-ticket lock. Context manager.

    Raises LockedError if another live process holds the lock.
    Stale locks (owning PID dead) are reclaimed automatically.

    Args:
        ticket: Ticket ID (e.g., "KLC-007")

    Raises:
        LockedError: If ticket is locked by another process

    Example:
        >>> with acquire_lock("KLC-007"):
        ...     # work on ticket
        ...     pass
    """
    lp = _lock_path(ticket)
    lp.parent.mkdir(parents=True, exist_ok=True)

    # Check for existing lock
    if lp.exists():
        try:
            rec = json.loads(lp.read_text(encoding="utf-8"))
            owner = int(rec.get("pid", 0))
        except (json.JSONDecodeError, ValueError):
            owner = 0

        if owner and owner != os.getpid() and _pid_alive(owner):
            raise LockedError(
                f"ticket {ticket!r} is locked by PID {owner} "
                f"(lock file: {lp}); wait or remove manually if stale"
            )

    # Acquire lock
    lp.write_text(
        json.dumps({"pid": os.getpid(), "at": _now()}) + "\n",
        encoding="utf-8",
    )

    try:
        yield
    finally:
        # Release lock
        try:
            lp.unlink()
        except OSError:
            pass
