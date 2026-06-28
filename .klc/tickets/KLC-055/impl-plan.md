# Implementation plan — KLC-055

## step-1 — Add `core/skills/identity.py` with `current()`

**Goal:** Create the new public identity module with `current()` implementing the email→name→USER→SystemExit fallback chain, covered by acceptance tests.
**RED:** `tests/test_identity.py::test_current_returns_email` — fails because `core/skills/identity.py` does not exist yet.
**GREEN:** Write `core/skills/identity.py` with `current()` as specified; all five acceptance tests pass.
**VERIFY:** `python -m pytest tests/test_identity.py -v`
**Expected:** `5 passed`
**COMMIT:** `KLC-055 step-1: add identity.current() helper in core/skills/identity.py`
**Affected files:** `core/skills/identity.py` (new), `tests/test_identity.py` (new)
**Interfaces:** `identity.current() -> str` — returns user identity string or raises `SystemExit`
**Depends on:** none
**Code sketch:**
```python
# core/skills/identity.py
from __future__ import annotations
import os
import subprocess


def current() -> str:
    """Return the current user's identity from git config, falling back
    to $USER.  Exits with setup instructions if nothing is configured."""
    for key in ("user.email", "user.name"):
        try:
            r = subprocess.run(
                ["git", "config", "--get", key],
                capture_output=True, text=True, timeout=5,
            )
            out = r.stdout.strip()
            if out:
                return out
        except (OSError, subprocess.TimeoutExpired):
            pass
    user_env = os.environ.get("USER", "").strip()
    if user_env:
        return user_env
    raise SystemExit(
        "KLC: git identity not configured.  Run:\n"
        "  git config --global user.email you@example.com\n"
        "  git config --global user.name  'Your Name'"
    )
```

## step-2 — Wire `intake.py` to use `identity.current()`

**Goal:** Replace the private `_git_user()` function in `core/phases/intake.py` with a delegation to `identity.current()`, eliminating the duplicated logic.
**RED:** `tests/test_intake_identity.py::test_intake_owner_uses_identity_module` — fails because `intake.py` still defines and calls `_git_user()` internally without importing `identity`.
**GREEN:** Remove `_git_user()` from `intake.py`; add `from core.skills import identity` and call `identity.current()` wherever `_git_user()` was called.
**VERIFY:** `python -m pytest tests/test_intake_identity.py tests/test_identity.py -v`
**Expected:** `6 passed`
**COMMIT:** `KLC-055 step-2: intake.py delegates owner lookup to identity.current()`
**Affected files:** `core/phases/intake.py`, `tests/test_intake_identity.py` (new)
**Interfaces:** none — `_git_user` is removed (private); callers within intake.py updated in place
**Depends on:** step-1
**Code sketch:**
```python
# core/phases/intake.py — diff sketch
-from __future__ import annotations
+from __future__ import annotations
+from core.skills import identity   # KLC-055

-def _git_user() -> str:
-    for key in ("user.email", "user.name"):
-        ...
-    return os.environ.get("USER", "unknown")

 # where _git_user() was called:
-        "owner": _git_user(),
+        "owner": identity.current(),
```
