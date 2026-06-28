---
ticket: KLC-055
kind: feature
authority: agent
track: S
risk_tags: [user-facing]
---

## Goals
Introduce a public `identity.current()` helper in `core/skills/identity.py` that returns the current user's identity from `git config user.email` (falling back to `user.name`, then `$USER`), and exits with a setup instruction if git config is entirely unset — replacing the private `_git_user()` in `core/phases/intake.py`.

## Acceptance Criteria
- [ ] AC-1: `identity.current()` returns `user.email` when `git config user.email` is set; returns `user.name` when only name is set; returns the `$USER` env-var value when neither git config key is set and `$USER` is non-empty.
- [ ] AC-2: When both git config keys and `$USER` are unset, `identity.current()` raises `SystemExit` with a non-empty message instructing the user to run `git config --global user.email <email>`.

## Affected
core/skills/identity: `core/skills/identity.py` (new file, no prior src line) [!ASSUMPTION if-false=scope-may-expand]
core/phases/intake: `_git_user`, src=core/phases/intake.py:77 — to be replaced with a call to `identity.current()`

## Estimate
complexity: 1
uncertainty: 0
risk: 0
manual: 0
total: 1

DISCOVERY_LITE_DONE
