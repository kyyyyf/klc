# Implementation plan — KLC-059

## step-1 — Add `klc remind` core logic as `remind.py`

**Goal:** Implement the `klc remind` verb as `core/phases/remind.py` with a `run(argv)` entry point; reads all tickets in `.klc/tickets/`, checks holder identity against current git user, calls `phase_completion.can_complete`, emits one line per completable-held ticket in `:work` state.
**RED:** `tests/integration/test_remind.py::test_remind_silent_when_nothing_to_do`, `tests/integration/test_remind.py::test_remind_fires_when_held_and_completable`, `tests/integration/test_remind.py::test_remind_silent_for_other_holder`
**GREEN:** Create `core/phases/remind.py` with `run(argv)` that implements the three behaviours; add `remind` to `LIFECYCLE_CMDS` in `scripts/klc`.
**VERIFY:** `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_remind.py -k "silent_when_nothing or fires_when or silent_for_other" -v`
**Expected:** `3 passed`
**COMMIT:** `KLC-059 step-1: add klc remind core logic`
**Affected files:** `core/phases/remind.py`, `scripts/klc`
**Interfaces:** `run(argv: list[str]) -> int` — exits 0 always; `--statusline` flag supported
**Depends on:** none
**Code sketch:**
```python
# core/phases/remind.py
import os, subprocess, sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
import phase_completion as _pc
from _paths import klc_tickets_dir

def _git_user() -> str:
    for key in ("user.email", "user.name"):
        try:
            r = subprocess.run(["git", "config", "--get", key],
                               capture_output=True, text=True, timeout=5)
            if r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    return os.environ.get("USER", "unknown")

def run(argv: list[str]) -> int:
    identity = _git_user()
    tickets_dir = klc_tickets_dir()
    if not tickets_dir.exists():
        return 0
    import lifecycle as _lc, phases as _ph
    for tdir in sorted(tickets_dir.iterdir()):
        if not (tdir / "meta.json").exists():
            continue
        try:
            meta = _lc.read_meta(tdir.name)
        except Exception:
            continue
        holder = meta.get("holder") or {}
        if holder.get("id") != identity:
            continue
        phase_val = meta.get("phase", "")
        if not phase_val.endswith(":work"):
            continue
        phase_id = phase_val.split(":")[0]
        try:
            ok, _ = _pc.can_complete(tdir.name, phase_id)
        except Exception:
            continue
        if ok:
            print(f"{tdir.name} {phase_id} is done — run klc ack")
    return 0
```

## step-2 — Wire hook delivery via `klc-plugin/hooks/remind.py` and `hooks.json`

**Goal:** Create a thin hook wrapper `klc-plugin/hooks/remind.py` that calls `klc remind` and always exits 0; register it as a second UserPromptSubmit hook in `hooks.json`.
**RED:** `tests/integration/test_remind.py::test_hook_always_exits_zero`, `tests/integration/test_remind.py::test_statusline_flag_emits_same_line`
**GREEN:** Create `klc-plugin/hooks/remind.py` mirroring `gate.py`'s structure; update `klc-plugin/hooks/hooks.json` to add the new hook entry.
**VERIFY:** `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_remind.py -k "hook_always_exits or statusline_flag" -v`
**Expected:** `2 passed`
**COMMIT:** `KLC-059 step-2: wire remind hook into hooks.json`
**Affected files:** `klc-plugin/hooks/remind.py`, `klc-plugin/hooks/hooks.json`
**Interfaces:** none — hook script has no importable API; it is invoked as a subprocess
**Depends on:** step-1
**Code sketch:**
```python
# klc-plugin/hooks/remind.py
"""remind.py — CC plugin hook that emits a forgotten-ack reminder.

Called by hooks.json on UserPromptSubmit. Runs `klc remind` for the
current identity. Always exits 0 (non-blocking — it is advisory only).

Exit codes (CC hook contract):
  0 — always; reminder text goes to stdout for CC to display
  2 — hook error; CC falls through (permissive)
"""
import os, shlex, subprocess, sys

def main() -> int:
    klc_bin = os.environ.get("KLC_BIN", "klc")
    klc_cmd = shlex.split(klc_bin) if " " in klc_bin else [klc_bin]
    try:
        result = subprocess.run(
            [*klc_cmd, "remind"],
            capture_output=False, timeout=10,
        )
    except Exception:
        return 0  # non-blocking: any error is silently swallowed
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

hooks.json addition:
```json
{
  "type": "command",
  "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/remind.py\"",
  "timeout": 10
}
```
