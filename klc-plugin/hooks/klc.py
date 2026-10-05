#!/usr/bin/env python3
"""klc.py — the single UserPromptSubmit hook of the klc plugin (KLC-180).

What it does on every prompt, in this order:
  1. reads the hook payload from stdin (garbage is ignored);
  2. finds the project (nearest `.klc/` above the payload cwd) and the active
     ticket (checked-out `feature/<key>-*` branch, else the one ticket this
     identity holds);
  3. starts one detached heartbeat push per held `:work` ticket that is due;
  4. prints ONE JSON object `{"systemMessage": "<line>"}` when the ticket waits
     for a human decision, and nothing otherwise.

Why it is built this way:
  * It NEVER blocks. Exit code is always 0 and stderr stays empty. The older
    blocking gate hook and its environment switches are retired; nothing reads
    them any more.
  * It never calls the `klc` CLI. All logic is `core/skills/klc_hook.py`, imported
    in-process, so a slow or broken `klc` cannot hold the prompt.
  * A watchdog (`os._exit(0)` at 1.8 s) caps the run below the 3 s timeout in
    hooks.json even if git or the disk hangs.
  * Stdlib only. Claude Code runs an installed plugin from its own cache, far from
    the checkout, so the framework root is looked up in this order: the
    project's `.klc/bin/klc` shim (`KLC_FW=`), then `KLC_FRAMEWORK_ROOT`, then the
    path relative to this file. `PROJECT_ROOT` is set from the resolved project.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading

WATCHDOG_SECONDS = 1.8


def _find_project(cwd: str) -> str | None:
    """The nearest ancestor of `cwd` (itself included) that holds a `.klc/` directory."""
    cur = os.path.abspath(cwd)
    while True:
        if os.path.isdir(os.path.join(cur, ".klc")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def _shim_framework(project: str | None) -> str | None:
    """The framework path written into the project's `.klc/bin/klc` shim (`KLC_FW="..."`)."""
    if not project:
        return None
    try:
        with open(os.path.join(project, ".klc", "bin", "klc"), encoding="utf-8") as f:
            m = re.search(r'^KLC_FW=["\']?([^"\'\n]+)', f.read(), re.MULTILINE)
        return m.group(1).strip() if m else None
    except BaseException:
        return None


def _has_framework(path: str | None) -> bool:
    return bool(path) and os.path.isfile(os.path.join(path, "core", "skills", "klc_hook.py"))


def _framework_root(project: str | None) -> str:
    """Lookup order: the project's shim, then `KLC_FRAMEWORK_ROOT`, then the path
    relative to this file (the plugin runs from inside the checkout)."""
    here = os.path.dirname(os.path.abspath(__file__))
    relative = os.path.dirname(os.path.dirname(here))   # klc-plugin/hooks -> repo root
    for cand in (_shim_framework(project), os.environ.get("KLC_FRAMEWORK_ROOT")):
        if _has_framework(cand):
            return cand
    return relative


def _payload_cwd() -> str:
    """The cwd from the hook payload when it names a directory, else the process cwd."""
    try:
        data = json.loads(sys.stdin.read())
        cwd = data.get("cwd") if isinstance(data, dict) else None
        if isinstance(cwd, str) and os.path.isdir(cwd):
            return cwd
    except BaseException:
        pass
    return os.getcwd()


def main() -> int:
    watchdog = threading.Timer(WATCHDOG_SECONDS, lambda: os._exit(0))
    watchdog.daemon = True
    watchdog.start()
    try:
        cwd = _payload_cwd()
        project = _find_project(cwd)
        if project:
            os.environ["PROJECT_ROOT"] = project           # also inherited by the heartbeat child
        sys.path.insert(0, os.path.join(_framework_root(project), "core", "skills"))
        import klc_hook
        from _paths import klc_tickets_dir
        ticket = klc_hook.active_ticket(cwd, klc_tickets_dir())
        me = klc_hook._identity_or_none()
        due = list(klc_hook.held_tickets(me)) if me else []
        if ticket and ticket not in due:
            due.append(ticket)
        for key in due:
            if klc_hook.heartbeat_due(key):
                klc_hook.spawn_heartbeat(key)
        if ticket:
            line = klc_hook.pending_line(ticket)
            if line:
                sys.stdout.write(json.dumps({"systemMessage": line}, ensure_ascii=False))
                sys.stdout.flush()
    except BaseException:
        pass
    finally:
        watchdog.cancel()
    return 0


if __name__ == "__main__":
    code = main()
    try:
        sys.stdout.flush()
    except BaseException:
        pass
    os._exit(code)
