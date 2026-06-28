# Agent prompt — KLC-055 · build:work · step-1

Ticket: **KLC-055** · track: **S** · kind: **unknown**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Introduce a public `identity.current()` helper in `core/skills/identity.py` that returns the current user's identity from `git config user.email` (falling back to `user.name`, then `$USER`), and exits with a setup instruction if git config is entirely unset — replacing the private `_git_user()` in `core/phases/intake.py`.

## Acceptance Criteria

- [ ] AC-1: `identity.current()` returns `user.email` when `git config user.email` is set; returns `user.name` when only name is set; returns the `$USER` env-var value when neither git config key is set and `$USER` is non-empty.
- [ ] AC-2: When both git config keys and `$USER` are unset, `identity.current()` raises `SystemExit` with a non-empty message instructing the user to run `git config --global user.email <email>`.

### Current step — step-1

**Add `core/skills/identity.py` with `current()`**

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

**Affected files**:


**Expected tests**:



### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.

### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/home/ek/projects/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-055 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-055/impl-plan.md`
- Full spec: `.klc/tickets/KLC-055/spec.md`
- Full test-plan: `.klc/tickets/KLC-055/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-055 step-1` and
run `klc step KLC-055 2` to get the next step's card,
or `klc ack KLC-055 --pick 1` if this was the last step.
