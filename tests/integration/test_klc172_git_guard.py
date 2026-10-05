"""KLC-172 step-5 (AC-12): the PreToolUse git-write guard for subagents."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
HOOKS = FW_ROOT / "klc-plugin" / "hooks"
GUARD = HOOKS / "git_guard.py"


def _run(stdin: str, env_extra: dict | None = None):
    env = {k: v for k, v in os.environ.items() if k != "KLC_SUBAGENT"}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(GUARD)], input=stdin,
                          capture_output=True, text=True, env=env, timeout=30)


def _payload(cmd, agent: bool = True, tool: str = "Bash") -> str:
    d = {"hook_event_name": "PreToolUse", "tool_name": tool,
         "tool_input": {"command": cmd}}
    if agent:
        d["agent_type"] = "general-purpose"
    return json.dumps(d)


DENIED = [
    "git checkout main", "git switch -c x", "git stash", "git stash pop",
    "git clean -fd", "git reset --hard HEAD~1", "git rebase main", "git push",
    "git push --force-with-lease origin x", "git -C /tmp/repo push",
    "git branch -D x", "git restore .", "cd /x && git push",
    "echo hi; git checkout -- .",
    # review round 1: wrappers, keywords, nested shells, option spellings
    "if true; then git push; fi", "for x in 1; do git push; done",
    "if false; then echo; else git push; fi",
    "command git push", "env git push", "env FOO=1 BAR=2 git push",
    "sudo git push", "/usr/bin/git push", "\\git push", "time git push",
    "nice git push", "exec git push", "echo x | xargs git push",
    "FOO=1 git push", 'sh -c "git push"', "bash -c 'git clean -fd'",
    "echo $(git push)", "echo `git push`", "git -Cx push",
    "git -c core.pager=cat push", "git -c alias.p=push p",
    "git -c alias.z='checkout' z main", "git -C /x -c user.name=a push",
    "git stash drop", "git stash push -m x",
    "git branch -m old new", "git worktree remove x",
]

ALLOWED = [
    "git status", "git diff main...HEAD", "git log --oneline -3",
    "git show HEAD:file", "git ls-files", "ls -la", "python3 -m pytest -q",
    'git commit -m "x"', "git add -A", "cat <<'EOF'\ngit push\nEOF",
    "git stash list", "git stash show -p", "git clean -n", "git clean --dry-run -d",
    "git branch", "git branch -a", "git branch --list 'x*'", "git worktree list",
    "env FOO=1 git status", "sudo git log", "bash -c 'git status'",
    "echo $(git rev-parse HEAD)", "git -C /x status", "git -c core.pager=cat log",
    "if true; then git diff; fi",
]


@pytest.mark.parametrize("cmd", DENIED)
def test_denies_git_writes_for_subagents(cmd):
    r = _run(_payload(cmd))
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert out["permissionDecisionReason"]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allows_readonly_and_non_git(cmd):
    r = _run(_payload(cmd))
    assert r.returncode == 0
    assert r.stdout == ""


def test_operator_session_not_blocked():
    r = _run(_payload("git push", agent=False))
    assert r.returncode == 0 and r.stdout == ""
    r = _run(_payload("git push", agent=False), {"KLC_SUBAGENT": "1"})
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("stdin", [
    "not json",
    _payload("git push", tool="Read"),
    json.dumps({"tool_name": "Bash", "tool_input": {}, "agent_type": "x"}),
])
def test_malformed_payload_allows(stdin):
    r = _run(stdin)
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


def test_hooks_json_registers_guard():
    data = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    entries = data["hooks"]["PreToolUse"]
    matched = [e for e in entries if e.get("matcher") == "Bash"]
    assert matched
    cmd = matched[0]["hooks"][0]["command"]
    assert "git_guard.py" in cmd
    assert cmd.startswith('python3 -c "') and "runpy" in cmd
