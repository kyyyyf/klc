---
ticket: KLC-010
authority: agent
last_generated: 2026-05-28T15:52:00Z
---

# Design options — KLC-010

## Option A — Minimal diff (inline branching in install_deps.py)

**recommended: false**

### Description

Add `--bootstrap`, `--dev` flags to existing `install_deps.py`. Keep all tool checks in `main()`, wrap them with conditional branches:
```python
if not args.bootstrap and not args.dev:
    # existing checks (node, npm, ast-grep, LSP servers, etc.)
if args.bootstrap:
    # Python, git, jinja2 only
if args.dev:
    # mutation testing tools only
```

Add new `core/skills/detect_languages.py` as standalone skill.

Add new `core/phases/setup.py` as command dispatcher entry.

Extend `core/phases/doctor.py` with `@check("project-tools")` function that reads `.klc/index/project-deps.json`.

### Trade-off

Keeps install_deps.py's complexity in one file (~400 LOC → ~500 LOC) but avoids refactoring existing tool-check logic. Quickest path to AC compliance.

### Affected files

- `scripts/install_deps.py` — add flag handling, wrap existing checks
- `core/skills/detect_languages.py` — NEW (60 LOC)
- `core/phases/setup.py` — NEW (120 LOC)
- `core/phases/doctor.py` — add `@check("project-tools")` (~30 LOC)
- `scripts/init.py` — update final output (5 LOC)
- `scripts/klc` — register `setup` subcommand (2 LOC)
- `README.md` — update install section (~20 lines)

Total: 1 new skill + 1 new phase + 4 modified files.

### Affected public APIs

- `install_deps.py`: new CLI flags `--bootstrap`, `--dev` (backward compat: no flags = existing behavior)
- `klc` dispatcher: new subcommand `klc setup`
- `klc doctor`: new flag `--strict` (backward compat: default WARN mode)

### New dependencies

None. All tools already in existing install_deps.py check list.

### Risks

- `install_deps.py` grows to ~500 LOC, harder to maintain long-term.
- If KLC-004/005 add more tools, need to update multiple branches in `main()`.
- Edge case: user runs `install_deps.py` without flags → still checks all tools (backward compat, but doesn't solve the problem for existing users unless they adopt new flags).

### Rollout

Immediate. No migration needed — new flags opt-in. README update guides new users to `--bootstrap` flow.

### Estimate

**S** (2-3 hours)
- 1h: refactor install_deps.py with branching
- 0.5h: write detect_languages.py
- 1h: write setup.py
- 0.5h: extend doctor.py

---

## Option B — Clean architecture (split install_deps into modules)

**recommended: true**

### Description

Refactor `install_deps.py` into modular structure:
- `core/deps/bootstrap.py` — checks Python, git, jinja2
- `core/deps/dev.py` — checks mutation testing tools
- `core/deps/project.py` — checks project-runtime tools (called by `klc setup`, not install_deps.py)
- `scripts/install_deps.py` — thin CLI dispatcher that imports and runs the correct module

New skill `core/skills/detect_languages.py`.

New phase `core/phases/setup.py` imports `core/deps/project.py`.

Extend `core/phases/doctor.py` with project-tool check.

### Trade-off

Cleaner separation of concerns, easier to extend for KLC-004/005. Requires more upfront work and creates new `core/deps/` package.

### Affected files

- `scripts/install_deps.py` — reduce to ~50 LOC (CLI dispatcher)
- `core/deps/__init__.py` — NEW
- `core/deps/bootstrap.py` — NEW (80 LOC)
- `core/deps/dev.py` — NEW (60 LOC)
- `core/deps/project.py` — NEW (150 LOC)
- `core/skills/detect_languages.py` — NEW (60 LOC)
- `core/phases/setup.py` — NEW (120 LOC)
- `core/phases/doctor.py` — add `@check("project-tools")` (~30 LOC)
- `scripts/init.py` — update final output (5 LOC)
- `scripts/klc` — register `setup` subcommand (2 LOC)
- `README.md` — update install section (~20 lines)

Total: 1 new package + 3 new modules + 1 new skill + 1 new phase + 4 modified files.

### Affected public APIs

Same as Option A:
- `install_deps.py`: new flags `--bootstrap`, `--dev`
- `klc` dispatcher: new subcommand `klc setup`
- `klc doctor`: new flag `--strict`

### New dependencies

None.

### Risks

- Creates new `core/deps/` package — need to decide if it belongs in `core/` (agent-facing) or `scripts/` (CLI-facing). Proposal: `core/deps/` since `setup.py` imports it.
- More files to maintain (4 new modules vs 1 refactored script).
- Backward compat: `install_deps.py` without flags must still work — dispatcher needs default mode that runs all checks (or warns about deprecation).

### Rollout

Immediate, but existing users may notice `install_deps.py` imports moved. If `sys.path` setup changes, could break external scripts that import from `install_deps.py` (unlikely, but possible).

### Estimate

**M** (4-5 hours)
- 2h: refactor install_deps.py into modules
- 0.5h: write detect_languages.py
- 1h: write setup.py
- 0.5h: extend doctor.py
- 0.5h: test backward compat for existing install_deps.py behavior

---

## Option C — Content change (generate install docs, no code execution)

### Description

Instead of refactoring `install_deps.py` (which checks and reports), generate **installation guide** documents that users follow manually. No CLI tool runs any checks.

- Create `docs/install/bootstrap.md` — instructions for minimal bootstrap
- Create `docs/install/dev.md` — instructions for framework dev tools
- Update `klc setup` to generate project-specific `docs/install/project-<languages>.md` dynamically based on detected languages
- Remove `install_deps.py` entirely
- `klc doctor` reads project-deps.json and reports status (no install hints, just PASS/FAIL)

### Trade-off

Eliminates complexity of cross-platform tool detection (no more Windows vswhere logic, no PATH checks). Shifts all install responsibility to users + their package managers. Reduces framework code by ~350 LOC, but loses convenience of "run script, see what's missing."

### Affected files

- `scripts/install_deps.py` — DELETED
- `docs/install/bootstrap.md` — NEW
- `docs/install/dev.md` — NEW
- `core/skills/detect_languages.py` — NEW (60 LOC)
- `core/phases/setup.py` — NEW (80 LOC, simpler — just generates docs)
- `core/phases/doctor.py` — add `@check("project-tools")` (~30 LOC)
- `scripts/init.py` — update final output to reference docs/install/ (5 LOC)
- `scripts/klc` — register `setup` subcommand (2 LOC)
- `README.md` — rewrite install section to point to docs/install/ (~30 lines)

Total: 3 new docs + 1 new skill + 1 new phase + 3 modified files - 1 deleted script.

### Affected public APIs

- `install_deps.py`: REMOVED (breaking change for users who run it directly)
- `klc` dispatcher: new subcommand `klc setup`
- `klc doctor`: new flag `--strict`

### New dependencies

None.

### Risks

- **Breaking change**: existing workflows that call `python scripts/install_deps.py` break.
- Loses cross-platform tool detection (e.g., Windows clangd via vswhere). Users on Windows must manually locate Visual Studio clangd.
- Users may skip setup steps and hit obscure failures later (no automated checking).
- Violates CONSTRAINT C-002 interpretation — user chose "manual install" (klc setup prints commands), not "no install tool at all."

### Rollout

Requires deprecation notice in one release, removal in next. Not immediate. Users must update their setup scripts.

### Estimate

**S** (2-3 hours)
- 1h: write docs/install/*.md
- 0.5h: write detect_languages.py
- 1h: write setup.py (simpler, just doc generation)
- 0.5h: extend doctor.py

But adds **migration cost** for existing users (~1 week coordination, not counted in ticket estimate).

---

## Recommendation

**Option B — Clean architecture** is recommended (user choice):

1. **Better long-term maintainability** — modular structure easier to extend when KLC-004/005 add new tools.
2. **Clear separation of concerns** — bootstrap, dev, and project tools in separate modules.
3. **Meets all ACs** — AC-1 (bootstrap mode), AC-2 (--project removed/deprecated), AC-3 (dev mode), AC-4..9 (same across all options).
4. **Backward compatible** — existing `install_deps.py` without flags still works (dispatcher mode).
5. **Prepares for future** — adding new language toolchains requires only extending `core/deps/project.py`, not editing multiple branches.

**Trade-off acknowledged**: requires M estimate (4-5 hours vs 2-3 for Option A) and creates new `core/deps/` package. User explicitly chose Option B for cleaner architecture.

**Option A rejected** because install_deps.py would grow to ~500 LOC with complex branching logic, harder to maintain long-term.

**Option C rejected** because:
- Violates user expectation (chose "manual install" = print commands, not "no install tool").
- Breaking change to existing `install_deps.py` users.
- Loses Windows clangd auto-detection (valuable feature).

---

## ADR needed?

**ADR_NEEDED=no**

Reasoning:
- No public API change (only new CLI flags, backward compat).
- No new external dependencies.
- No data schema / persistence change (project-deps.json is ephemeral, not committed).
- No cross-module boundary crossed (all changes within install/setup/doctor; skills/detect_languages.py is standalone).
- Cleaner option (B) rejected for *pragmatic* reasons (speed), but complexity delta is small (160 LOC diff) — not worth ADR overhead.

If this decision reverses and Option B is chosen later, ADR can be written at that time.
