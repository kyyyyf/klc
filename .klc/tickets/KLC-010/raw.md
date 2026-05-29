---
ticket: KLC-010
kind_hint: tech
created: 2026-05-28T15:40:45Z
---
# KLC-010 — Layered dependency installation (bootstrap + project setup)

## Context

`scripts/install_deps.py` currently installs *everything* required for *every* language the framework can handle (Python tooling, node+npm, ast-grep, uv, etc.) at install time. This:

1. Forces the user to install tools they may never need (e.g. node+npm for a pure C++ repo).
2. Runs *before* the framework knows what kind of project it will be applied to (`install_deps.py` runs after framework download but before `klc init` detects project languages).
3. Lumps framework-dev tools (e.g. tools used to develop klc itself) together with project-runtime tools (tools used by klc skills against a target repo).

Result: friction on first install, false-positive doctor failures, unclear which dependencies are mandatory vs optional.

## Problem

- No separation between "what klc itself needs to start running" and "what your specific project needs to use klc fully".
- `klc doctor` flags as FAIL tools that the project may not actually use (e.g. ast-grep on a no-AST project).
- No machine-readable manifest of what the *current* project requires.
- No way for klc dev contributors to install only dev-time tools without project-runtime tools.

## Proposed solution (layered installation)

### Phase 1 — Bootstrap (`install_deps.py --bootstrap`)
Install *only* the minimum required for `klc init` to run:
- Python 3.11+
- git
- jinja2 (for template rendering)

After bootstrap, `klc init` is runnable. Nothing else is forced on the user.

### Phase 2 — Project setup (new command: `klc setup`)
Run after `klc init` has detected project languages. Behavior:
1. Detect languages via existing inventory.json + profile.yml.
2. Compute the required tool set per language (e.g. C++ → scip-clang; TS → tsc; Python → ruff).
3. **Print the install commands** (manual mode — do not auto-install).
4. Write `.klc/index/project-deps.json` (auto-generated, not committed) listing required + optional tools and their detected status.

User then runs the printed commands manually.

### Phase 3 — Validation (`klc doctor`)
- Read `.klc/index/project-deps.json` and only check tools listed there.
- Default: missing tool → WARN.
- `--strict` flag: missing tool → FAIL (for CI use).

### Dev mode (`install_deps.py --dev`)
For klc framework contributors only. Installs framework-dev tools (linters, test runners against klc itself, etc.) separately from project-runtime tools.

## Acceptance criteria

- AC-1: `install_deps.py --bootstrap` installs ≤3 dependencies (Python deps + git check).
- AC-2: `install_deps.py --project` is removed or refactored (project deps now via `klc setup`).
- AC-3: `install_deps.py --dev` installs framework dev tools only.
- AC-4: New skill `core/skills/detect_languages.py` returns set of languages from inventory + profile.
- AC-5: New command `klc setup` prints required tool install commands and writes `.klc/index/project-deps.json`.
- AC-6: `klc doctor` reads `.klc/index/project-deps.json`. Missing tools → WARN by default, FAIL with `--strict`.
- AC-7: `klc init` final output includes a "Next: run `klc setup`" hint.
- AC-8: `tests/smoke.py` and `tests/e2e_pipeline.py` pass.
- AC-9: README.md install section updated to reflect 3-step flow (bootstrap → init → setup).

## Out of scope

- Auto-install of project tools (explicit user decision: manual only).
- Per-OS package manager abstraction (keep current heuristics).
- Replacing `klc doctor` with a different validator.
- Re-implementing language detection (reuse what `klc init` already does).

## Design decisions (user-confirmed)

- **Auto-install level**: Manual — only print commands.
- **doctor strictness**: Configurable via `--strict` flag (default WARN).
- **Manifest location**: `.klc/index/project-deps.json` (auto-generated, like `inventory.json` and `depgraph.json`; not committed).
- **Dev vs runtime**: Separate `--dev` mode for framework contributors.

## Estimate

- Complexity: 3 (new command + skill + refactor existing installer)
- Uncertainty: 2 (interaction with KLC-004/005 unknown — they may add new tools)
- Risk: 1 (regression in install flow blocks new users)
- Manual: 1 (test on clean checkout)
- Total: 7
- Track: M

## Related

- **Coordinates with KLC-004** (C++ call graph — adds scip-clang to project deps).
- **Coordinates with KLC-005** (TS call graph — adds tsc to project deps).
- **Builds on KLC-008** (e2e tests as safety net for refactor).
- Independent of KLC-003 (publish adapters).

## Notes

Run after KLC-003 lands (independent quick win first), and before KLC-004/005 (so they can register their tools through the new mechanism).
