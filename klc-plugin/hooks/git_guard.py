#!/usr/bin/env python3
"""git_guard.py — CC plugin hook (PreToolUse, matcher Bash) that stops
subagents from running git commands that destroy history or touch remotes.

Why it exists: a spawned reviewer once ran `git clean` and destroyed
untracked work. A prompt rule ("never write to git") is advisory; this hook
makes it mechanical. Only subagents are restricted: the payload carries
`agent_type` when the tool call comes from a subagent, and `KLC_SUBAGENT=1`
in the environment marks one explicitly. The operator's own session is never
blocked. `git commit` and `git add` stay allowed on purpose — the guard
targets history-destroying and remote operations, not ordinary building.

Contract: always exit 0, never write to stderr. Print the deny JSON on stdout
only when denying; any parse error or unexpected shape fails open (silent).
Standalone: stdlib only, no imports from core/.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import Mapping

_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w]*)\1")

_ASSIGN_RE = re.compile(r"^[A-Za-z_]\w*=")
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_CMD_KEYWORDS = {"then", "do", "else", "elif", "if", "while", "until", "time",
                 "exec", "command", "builtin", "nohup", "!", "{", "(", "}", ")"}
# wrapper -> options that take a separate argument
_WRAPPERS = {"sudo": {"-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U"},
             "nice": {"-n"}, "ionice": {"-c", "-n", "-p"}, "setsid": set(),
             "env": {"-u", "-C", "-S"}, "timeout": {"-s", "-k"},
             "xargs": {"-n", "-I", "-P", "-L", "-s", "-d", "-E", "-a"}}
# git global options that take a separate argument
_GIT_ARG_OPTS = {"-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                 "--config-env"}
_MAX_DEPTH = 5

ALWAYS_DENIED = {"checkout", "switch", "stash", "clean", "rebase", "push",
                 "restore", "filter-branch"}


def _strip_heredocs(cmd: str) -> str:
    """Drop heredoc bodies: the lines after a `<<MARK` line up to MARK."""
    out: list[str] = []
    pending: list[str] = []
    for line in cmd.split("\n"):
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        out.append(line)
        pending.extend(m.group(2) for m in _HEREDOC_RE.finditer(line))
    return "\n".join(out)


def _segments(cmd: str) -> list[str]:
    """Split a shell command on && || ; | and newlines, outside quotes and
    without heredoc bodies."""
    text = _strip_heredocs(cmd)
    segs: list[str] = []
    buf: list[str] = []
    quote = ""
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 1
            elif c == quote:
                quote = ""
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif c == "\\" and i + 1 < len(text):
            buf.append(c)
            buf.append(text[i + 1])
            i += 1
        elif c in ";|&\n":
            if c == "&" and not (i + 1 < len(text) and text[i + 1] == "&"):
                buf.append(c)  # `2>&1`, `&>`, background `&`
            else:
                segs.append("".join(buf))
                buf = []
                if c in "|&" and i + 1 < len(text) and text[i + 1] == c:
                    i += 1
        else:
            buf.append(c)
        i += 1
    segs.append("".join(buf))
    return [s.strip() for s in segs if s.strip()]


def _short_flag(tokens: list[str], letters: str) -> bool:
    return any(t.startswith("-") and not t.startswith("--")
               and any(ch in t[1:] for ch in letters) for t in tokens)


def _denied(verb: str, tokens: list[str]) -> bool:
    """Is `git <verb> <tokens>` a denied write? Read-only subcommands of a
    denied verb (stash list/show, clean -n, branch listing, worktree list)
    stay allowed."""
    if verb == "stash":
        return not (tokens and tokens[0] in ("list", "show"))
    if verb == "clean":
        return not ("--dry-run" in tokens or _short_flag(tokens, "n"))
    if verb in ALWAYS_DENIED:
        return True
    if verb == "reset":
        return "--hard" in tokens or "--merge" in tokens
    if verb == "branch":
        return ("--delete" in tokens or "--move" in tokens
                or _short_flag(tokens, "dDmM"))
    if verb == "update-ref":
        return "-d" in tokens
    if verb == "reflog":
        return bool(tokens) and tokens[0] == "expire"
    if verb == "worktree":
        return bool(tokens) and tokens[0] == "remove"
    return False


def _split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _substitutions(text: str) -> list[str]:
    """Bodies of `$( ... )` and backtick substitutions, innermost first, so a
    nested command is scanned even when the outer word looks harmless."""
    bodies: list[str] = []
    for _ in range(_MAX_DEPTH):
        found = re.findall(r"\$\(([^()]*)\)", text) + re.findall(r"`([^`]*)`", text)
        if not found:
            break
        bodies.extend(found)
        text = re.sub(r"\$\([^()]*\)|`[^`]*`", " ", text)
    return bodies


def _skip_options(tokens: list[str], takes_arg: set[str], assigns: bool) -> list[str]:
    while tokens:
        t = tokens[0]
        if assigns and _ASSIGN_RE.match(t):
            tokens = tokens[1:]
        elif t.startswith("-") and len(t) > 1:
            tokens = tokens[2:] if t in takes_arg else tokens[1:]
        else:
            break
    return tokens


def _unwrap(tokens: list[str]) -> list[str]:
    """Drop leading shell keywords, VAR=value assignments and wrappers
    (env, sudo, nice, xargs, ...) so `tokens[0]` is the real command."""
    while tokens:
        t = tokens[0].lstrip("({!")
        if not t:
            tokens = tokens[1:]
            continue
        tokens = [t] + tokens[1:]
        base = t.rsplit("/", 1)[-1]
        if _ASSIGN_RE.match(t) or t in _CMD_KEYWORDS:
            tokens = tokens[1:]
        elif base in _WRAPPERS:
            tokens = _skip_options(tokens[1:], _WRAPPERS[base], base == "env")
            if base == "timeout" and tokens:
                tokens = tokens[1:]            # the duration
        else:
            break
    return tokens


def _alias_denied(value: str, depth: int) -> bool:
    """Does an alias definition (`alias.X=<value>`) expand to a denied write?"""
    if value.startswith("!"):
        return _scan_command(value[1:], depth + 1) is not None
    parts = _split(value)
    return bool(parts) and _denied(parts[0], parts[1:])


def _scan_tokens(tokens: list[str], depth: int) -> str | None:
    tokens = _unwrap(tokens)
    if not tokens:
        return None
    base = tokens[0].rsplit("/", 1)[-1]
    if base in _SHELLS:
        for i, t in enumerate(tokens[1:], 1):
            if re.fullmatch(r"-[a-z]*c[a-z]*", t) and i + 1 < len(tokens):
                return _scan_command(tokens[i + 1], depth + 1)
        return None
    if base == "eval":
        return _scan_command(" ".join(tokens[1:]), depth + 1)
    if base != "git":
        return None
    args = tokens[1:]
    i = 0
    aliases: list[str] = []
    while i < len(args):
        a = args[i]
        if a in _GIT_ARG_OPTS:
            i += 2
        elif a == "-c":
            if i + 1 < len(args):
                aliases.append(args[i + 1])
            i += 2
        elif a.startswith("-c") and not a.startswith("--") and len(a) > 2:
            aliases.append(a[2:])
            i += 1
        elif a.startswith("-"):                 # -Cdir, --no-pager, --x=y, -P ...
            i += 1
        else:
            break
    if i >= len(args):
        return None
    verb, rest = args[i].strip(")`"), args[i + 1:]
    if verb == "config":
        for j, t in enumerate(rest):           # `git config alias.X <value>`
            if t.startswith("alias."):
                aliases.append(t if "=" in t or j + 1 >= len(rest)
                               else f"{t}={rest[j + 1]}")
    for kv in aliases:
        name, _, value = kv.partition("=")
        if name.startswith("alias.") and _alias_denied(value, depth):
            return f"git alias to a write ({name})"
    if _denied(verb, rest):
        return f"git {verb}"
    return None


def _scan_command(cmd: str, depth: int = 0) -> str | None:
    """The deny reason for a (possibly compound, possibly nested) command."""
    if depth > _MAX_DEPTH:
        return None
    for body in _substitutions(cmd):
        why = _scan_command(body, depth + 1)
        if why:
            return why
    for seg in _segments(cmd):
        why = _scan_tokens(_split(seg), depth)
        if why:
            return why
    return None


def decide(payload: dict, env: Mapping[str, str]) -> str | None:
    """Return the deny reason, or None to allow."""
    if not (payload.get("agent_type") or env.get("KLC_SUBAGENT") == "1"):
        return None
    if payload.get("tool_name", "Bash") != "Bash":
        return None
    cmd = (payload.get("tool_input") or {}).get("command")
    if not isinstance(cmd, str) or not cmd:
        return None
    why = _scan_command(cmd)
    if why:
        return (f"klc git guard: subagents must not run `{why}` "
                "— leave git writes to the operator")
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
            return 0
        reason = decide(payload, os.environ)
        if reason:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason}}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
