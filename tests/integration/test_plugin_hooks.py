#!/usr/bin/env python3
"""The plugin's hook contract (KLC-180 step-2 replaced the gate/remind/heartbeat trio).

One UserPromptSubmit hook (`klc.py`) that never blocks, plus the PreToolUse git
guard (covered by test_klc172_git_guard.py). Claude Code's documented contract:
only exit 2 (or `decision: block`) blocks a prompt; stdout JSON may carry only the
documented keys. The hook is run here exactly as Claude Code runs it: through the
hooks.json command with ${CLAUDE_PLUGIN_ROOT} resolved.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_DIR = FW_ROOT / "klc-plugin"
USER_PROMPT_SUBMIT_KEYS = {"decision", "reason", "continue", "stopReason",
                           "systemMessage", "suppressOutput", "hookSpecificOutput",
                           "additionalContext", "sessionTitle"}


def _commands(event: str) -> list[str]:
    data = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    cmds = [h["command"] for g in data["hooks"][event] for h in g["hooks"]]
    assert cmds, f"no {event} command registered"
    return cmds


def _run(command: str, root: Path, stdin: str):
    env = {**os.environ, "PROJECT_ROOT": str(root)}
    env.pop("KLC_FRAMEWORK_ROOT", None)
    resolved = command.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_DIR))
    return subprocess.run(shlex.split(resolved), capture_output=True, text=True, env=env,
                          input=stdin, cwd=str(root), timeout=20)


def test_hooks_json_exists_and_declares_no_mcp() -> None:
    assert (PLUGIN_DIR / "hooks" / "hooks.json").exists()
    data = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert "mcpServers" not in data


def test_registered_prompt_hook_follows_contract_and_never_blocks() -> None:
    for payload in (json.dumps({"prompt": "what next?"}), "", "not json", "[]"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".klc").mkdir()
            for command in _commands("UserPromptSubmit"):
                r = _run(command, root, payload)
                assert r.returncode == 0, (payload, r)          # never exit 2
                assert r.stderr == "", r.stderr
                text = r.stdout.strip()
                if text:
                    assert set(json.loads(text)) <= USER_PROMPT_SUBMIT_KEYS


def test_hook_launcher_exits_zero_when_script_missing() -> None:
    command = _commands("UserPromptSubmit")[0].replace("hooks/klc.py", "hooks/does-not-exist.py")
    with tempfile.TemporaryDirectory() as tmp:
        r = _run(command, Path(tmp), "{}")
    assert (r.returncode, r.stdout) == (0, "")


def test_pending_decision_reaches_the_user_as_system_message() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q", "-b", "feature/klc-960-x"], cwd=root, check=True)
        tdir = root / ".klc" / "tickets" / "KLC-960"
        tdir.mkdir(parents=True)
        (tdir / "meta.json").write_text(json.dumps({
            "ticket": "KLC-960", "kind": "feature", "kind_source": "user",
            "phase": "design:ack-needed", "phase_history": [], "track": "M",
            "affected_modules": [], "estimate": None, "jira_url": None,
            "created": "2026-01-01T00:00:00Z"}), encoding="utf-8")
        for command in _commands("UserPromptSubmit"):
            r = _run(command, root, "{}")
            assert r.returncode == 0
            obj = json.loads(r.stdout)
            assert list(obj) == ["systemMessage"] and "KLC-960" in obj["systemMessage"]
