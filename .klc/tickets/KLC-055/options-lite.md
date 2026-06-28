## Approach options
- Option A: New module `core/skills/identity.py` with `current()` — extracts the private `_git_user()` from `intake.py` into a dedicated public module; `intake.py` calls `identity.current()` instead. Prompt-on-unset is a `sys.exit` with instructions (not interactive prompt). Trade-off: clean separation, but requires updating the intake caller.
- Option B: Expose `_git_user` as a public function directly in `core/phases/intake.py` — minimal diff, no new file. Trade-off: breaks the single-responsibility principle and makes KLC-056 (phase-holder stamping) depend on the intake phase module rather than a dedicated helper.
- Option C: Add `identity.current()` to `core/skills/_paths.py` alongside other shared helpers — avoids a new file. Trade-off: _paths.py is about path resolution, not identity; mixing concerns makes the module harder to understand.

Picked: Option A — a dedicated `core/skills/identity.py` module keeps the identity concern isolated, is the natural home for KLC-056's phase-holder stamping to import from, and avoids cross-layer dependencies between `core/phases` and `core/skills`.
