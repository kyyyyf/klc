#!/usr/bin/env python3
"""Test that the klc-plugin declares no MCP server (AC-6)."""
from __future__ import annotations

from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_DIR = FW_ROOT / "klc-plugin"


def test_no_mcp_server_declared() -> None:
    """No .mcp.json or mcp-related config in the plugin directory."""
    assert PLUGIN_DIR.exists(), f"klc-plugin/ missing at {PLUGIN_DIR}"

    # CC plugins declare MCP servers via *.mcp.json files
    mcp_files = list(PLUGIN_DIR.rglob("*.mcp.json"))
    assert not mcp_files, (
        f"Plugin must not declare MCP servers; found: {[str(f) for f in mcp_files]}"
    )

    # hooks.json must not reference an mcpServers key
    hooks_file = PLUGIN_DIR / "hooks" / "hooks.json"
    if hooks_file.exists():
        import json
        hooks = json.loads(hooks_file.read_text(encoding="utf-8"))
        assert "mcpServers" not in hooks, (
            "hooks/hooks.json must not declare mcpServers"
        )
