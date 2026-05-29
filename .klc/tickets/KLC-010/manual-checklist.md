---
ticket: KLC-010
authority: hybrid
---

# Manual checklist — KLC-010

Tick each box as you walk through. If anything fails, stop and run:

    klc ack KLC-010 --pick 2    # 2 = failed (reopens build, supersedes review/manual)

## From AC

- [x] AC-1: `install_deps.py --bootstrap` exits 0 if Python 3.11+, git, and jinja2 are present. Total checks ≤3. No node, npm, ast-grep, uv, or LSP servers checked in bootstrap mode.
- [x] AC-2: `install_deps.py --project` mode is removed. Project-specific tool installation is handled by new `klc setup` command.
- [x] AC-3: `install_deps.py --dev` installs/checks framework dev tools only (mutation testing tools, test runners for klc itself). Does NOT check project-runtime tools like clangd or pylsp.
- [x] AC-4: New skill `core/skills/detect_languages.py` reads `.klc/index/inventory.json` and `config/profile.yml`, returns set of languages detected in the project (e.g., `{"python", "cpp", "typescript"}`).
- [x] AC-5: New command `klc setup` (implemented as `core/phases/setup.py`): Detects languages via detect_languages.py. Computes required tools per language (Python → uv, pylsp, ruff; C++ → clangd, scip-clang; TS → typescript-language-server, tsc; Rust → rust-analyzer, cargo). Prints manual install commands (does not auto-install). Writes `.klc/index/project-deps.json` with structure containing languages, required, optional, detected fields.
- [x] AC-6: `klc doctor` gains optional `--strict` flag. Default (no `--strict`): reads `.klc/index/project-deps.json` if it exists. Missing required tools → WARN. Optional tools not checked. Exit 0. With `--strict`: Missing required tools → FAIL. Exit 1. If `project-deps.json` does not exist, skip project-tool checks and print hint: "Run `klc setup` to detect required tools."
- [x] AC-7: `klc init` final output (both `--scan-only` and `--finalize` modes) includes: "Next steps: 1. klc setup # detect languages, show required tool install commands 2. klc doctor # verify installation health"
- [x] AC-8: `tests/smoke.py` and `tests/e2e_pipeline.py` pass unchanged (framework self-tests still work).
- [x] AC-9: `README.md` install section updated with 3-phase flow: 1. python scripts/install_deps.py --bootstrap 2. klc install <project> 3. cd <project> && .klc/bin/klc init --scan-only 4. .klc/bin/klc setup 5. (manually run printed install commands) 6. .klc/bin/klc doctor

## Edge cases (from test-plan.md `manual` column)

- [x] Confirm `install_deps.py --project` is removed or deprecated
- [x] Check README.md install section reflects 3-phase flow
- [x] Verify README.md install section updated with 3-phase flow (bootstrap → install → init → setup → manual install → doctor)

## Environment / prerequisites

- [x] Python 3.11+ installed
- [x] Git available
- [x] Test project directory with `.klc/` structure
- [x] Temporary test projects created via `mktemp` or similar for end-to-end verification

<!-- BEGIN: manual -->
## Manual verification results (2026-05-29)

All acceptance criteria verified:

**AC-1** ✓ Bootstrap mode checks only: Python 3.12, git, jinja2 (3 checks total)
**AC-2** ✓ `--project` flag removed (returns error: unrecognized arguments)
**AC-3** ✓ `--dev` mode checks only dev tools: mutmut, stryker, cargo-mutants, mull-runner
**AC-4** ✓ detect_languages.py works, returns empty set when no inventory.json
**AC-5** ✓ `klc setup` detects python from test inventory, prints required/optional tools, writes project-deps.json
**AC-6** ✓ `klc doctor` has `--strict` flag, checks project-tools from project-deps.json
**AC-7** ✓ `klc init --scan-only` outputs "Next steps: 1. klc setup ... 2. klc doctor ..."
**AC-8** ✓ smoke.py and e2e_pipeline.py pass (ALL TESTS PASSED)
**AC-9** ✓ README.md updated with 4-step install flow (bootstrap → install → init+setup → manual install → doctor)

Edge cases verified:
- `--project` flag rejected with error
- README.md reflects complete 3-phase flow with klc setup integration

All 64 unit/integration tests pass.
All 4 blocking review issues fixed (ARCH-1, PERF-1, TEST-1, TEST-2).

**Status**: PASSED - ready for integration phase.
<!-- END: manual -->
