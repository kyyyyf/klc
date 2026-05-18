#!/usr/bin/env python3
"""run-hook.py — invoke a profile hook with a standard file-list input
and JSON output.

Usage:
    run-hook.py <hook-name> <files-list-file> <out-json-file>

The active profile's manifest.yml must have:

    hooks:
      <hook-name>: profiles/<profile>/hooks/<script>

If the hook is not declared the skill writes an empty-findings JSON and
exits 0 — callers don't have to special-case missing hooks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def framework_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def main() -> int:
    if len(sys.argv) != 4:
        sys.stderr.write("usage: run-hook.py <hook-name> <files-list> <out-json>\n")
        return 2
    hook_name, files_in, out_json = sys.argv[1], sys.argv[2], sys.argv[3]

    resolve = framework_root() / "core" / "skills" / "profile-resolve.py"
    try:
        result = subprocess.run(
            [sys.executable, str(resolve), "--field", "hooks"],
            check=True, capture_output=True, text=True,
        )
        hooks = json.loads(result.stdout or "{}")
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        hooks = {}

    rel = hooks.get(hook_name, "")
    if not rel:
        Path(out_json).write_text(json.dumps({
            "validated_files": 0,
            "findings":        [],
            "skipped":         [],
            "tools_missing":   [],
            "note":            f"hook '{hook_name}' not declared in active profile",
        }, indent=2), encoding="utf-8")
        return 0

    # `rel` is a path relative to framework root (e.g.
    # "profiles/generic/hooks/validate-syntax.sh"). In Layout B
    # framework_root() is the klc checkout itself — no `framework/`
    # prefix.
    hook_path = framework_root() / rel
    if not hook_path.exists():
        sys.stderr.write(f"run-hook: {hook_path} not found\n")
        return 1
    # On Windows executable bit is meaningless; trust the file's
    # suffix instead (.py runs via sys.executable; .sh via bash; .ps1
    # via pwsh). POSIX: honour the x bit.
    if sys.platform != "win32" and not os.access(hook_path, os.X_OK):
        sys.stderr.write(
            f"run-hook: {hook_path} exists but is not executable; chmod +x it\n"
        )
        return 1

    suffix = hook_path.suffix.lower()
    if suffix == ".py":
        argv = [sys.executable, str(hook_path), files_in, out_json]
    elif suffix == ".ps1":
        argv = ["pwsh", "-File", str(hook_path), files_in, out_json]
    elif suffix == ".sh" or not suffix:
        argv = [str(hook_path), files_in, out_json]
    else:
        argv = [str(hook_path), files_in, out_json]

    # os.execv is POSIX-semantics only; use subprocess so Windows
    # gets identical behaviour.
    r = subprocess.run(argv)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
