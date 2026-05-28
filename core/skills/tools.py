"""tools.py — resolve external tools by PATH, with tools.json fallback.

Some external CLIs (clangd especially) are not installed in PATH on
Windows even when they exist on disk (Visual Studio bundles clangd at
`VC\\Tools\\Llvm\\bin\\clangd.exe` but doesn't add it to PATH).
`install-deps.py` detects these via vswhere and writes the resolved
path to `.klc/config/tools.json`:

    { "clangd": {"path": "C:/Program Files/.../clangd.exe"},
      "ast-grep": {"path": "..."} }

Callers use `resolve_tool("clangd")` instead of `shutil.which("clangd")`
so the override kicks in automatically.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
from core.shared.paths import klc_config_dir  # noqa: E402


_TOOLS_FILE_CACHE: dict[str, dict] | None = None


def _load_tools_file() -> dict[str, dict]:
    global _TOOLS_FILE_CACHE
    if _TOOLS_FILE_CACHE is not None:
        return _TOOLS_FILE_CACHE
    path = klc_config_dir() / "tools.json"
    if not path.exists():
        _TOOLS_FILE_CACHE = {}
        return _TOOLS_FILE_CACHE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _TOOLS_FILE_CACHE = {}
        return _TOOLS_FILE_CACHE
    if not isinstance(data, dict):
        _TOOLS_FILE_CACHE = {}
        return _TOOLS_FILE_CACHE
    _TOOLS_FILE_CACHE = data
    return data


def resolve_tool(name: str) -> Path | None:
    """Return the absolute Path to the tool if found, else None.

    Resolution order:
      1. `shutil.which(name)` — standard PATH lookup.
      2. `.klc/config/tools.json` — project-recorded override.
    """
    hit = shutil.which(name)
    if hit:
        return Path(hit)
    tools = _load_tools_file()
    entry = tools.get(name)
    if isinstance(entry, dict):
        p = entry.get("path")
        if isinstance(p, str) and Path(p).exists():
            return Path(p)
    return None


def record_tool(name: str, path: Path | str) -> None:
    """Write `.klc/config/tools.json` so future `resolve_tool(name)`
    returns this path. Overwrites an existing entry for the same name."""
    global _TOOLS_FILE_CACHE
    cfg_dir = klc_config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    file = cfg_dir / "tools.json"
    data: dict[str, dict] = {}
    if file.exists():
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, json.JSONDecodeError):
            data = {}
    data[name] = {"path": str(path)}
    file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    _TOOLS_FILE_CACHE = data


def _reset_cache() -> None:
    """Test helper."""
    global _TOOLS_FILE_CACHE
    _TOOLS_FILE_CACHE = None
