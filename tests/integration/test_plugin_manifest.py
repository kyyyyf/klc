#!/usr/bin/env python3
"""Test that the klc-plugin directory has a valid installable structure (AC-1).

A CC plugin is a directory with commands/ (slash commands) and agents/
(subagents) subdirectories. This test checks the static commands are present
and well-formed after plugin-gen runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_DIR = FW_ROOT / "klc-plugin"
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


LIFECYCLE_CMDS = ("intake", "status", "next", "ack", "ship", "jump", "abort", "step", "run")


def _has_frontmatter(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    return content.startswith("---\n") or content.startswith("---\r\n")


def test_manifest_valid() -> None:
    """Plugin directory has commands/ and agents/ directories."""
    assert PLUGIN_DIR.exists(), (
        f"klc-plugin/ directory missing at {PLUGIN_DIR}"
    )
    assert (PLUGIN_DIR / "commands").is_dir(), "klc-plugin/commands/ directory missing"
    assert (PLUGIN_DIR / "agents").is_dir(), (
        "klc-plugin/agents/ missing — run `klc plugin-gen` to generate"
    )


def test_commands_present() -> None:
    """Each lifecycle verb has a command file with valid frontmatter."""
    cmd_dir = PLUGIN_DIR / "commands"
    for verb in LIFECYCLE_CMDS:
        f = cmd_dir / f"{verb}.md"
        assert f.exists(), f"klc-plugin/commands/{verb}.md missing"
        assert _has_frontmatter(f), f"commands/{verb}.md has no YAML frontmatter"


def test_commands_have_description() -> None:
    """Each command's frontmatter declares a description field."""
    import re
    cmd_dir = PLUGIN_DIR / "commands"
    for verb in LIFECYCLE_CMDS:
        f = cmd_dir / f"{verb}.md"
        if not f.exists():
            continue
        content = f.read_text(encoding="utf-8")
        assert re.search(r"^description:", content, re.MULTILINE), (
            f"commands/{verb}.md frontmatter missing 'description:'"
        )


def test_no_mcp_server_files() -> None:
    """No .mcp.json files in the plugin (no MCP server declared)."""
    mcp_files = list(PLUGIN_DIR.rglob("*.mcp.json"))
    assert not mcp_files, (
        f"Plugin must declare no MCP servers; found: {mcp_files}"
    )
