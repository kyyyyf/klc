---
ticket: KLC-010
authority: agent
last_generated: 2026-05-29T00:00:00Z
chosen_option: B
---

# Implementation plan — KLC-010

Chosen option: **B — Clean architecture (split install_deps into modules)**

## Overview

Refactor `install_deps.py` into modular structure with `core/deps/` package containing bootstrap, dev, and project tool checks. Add new `klc setup` command for language-specific tool setup. Extend `klc doctor` with project-tool validation.

Total: 7 steps, each representing one logical commit.

---

## [step-1] Create core/deps package structure

### Description

Create new `core/deps/` package with `__init__.py` and shared utilities extracted from current `install_deps.py`:
- Logging functions (`log`, `warn`, `err`)
- Platform detection (`platform_tag`)
- Tool checking helpers (`_has`, `_check`, `_check_python_lib`)

No behavioral changes yet — just code organization prep.

### Affected files

- `core/deps/__init__.py` — NEW (80 LOC)
  - Import logging, platform detection, tool check utilities
  - Re-export for use by bootstrap/dev/project modules

### Expected tests

- `tests/test_deps_utils.py::test_platform_detection` — verify `platform_tag()` returns correct OS
- `tests/test_deps_utils.py::test_tool_check_helpers` — verify `_has()` finds tools on PATH

### Notes

Foundation step. No user-facing changes.

---

## [step-2] Implement bootstrap module

### Description

Create `core/deps/bootstrap.py` with minimal dependency checks:
- Python 3.11+ (via `sys.version_info`)
- git (via `shutil.which`)
- jinja2 (via `__import__`)

Exit 0 if all present, exit 1 with install instructions otherwise.

### Affected files

- `core/deps/bootstrap.py` — NEW (80 LOC)
  - `check_bootstrap() -> int` function
  - Returns 0/1, logs to .klc/logs/install-deps.log

### Expected tests

- `tests/test_install_deps.py::test_bootstrap_mode` — AC-1 coverage
- Mock `sys.version_info` to test Python version check
- Mock `shutil.which` to test git presence

### Notes

Satisfies AC-1: ≤3 dependency checks in bootstrap mode.

---

## [step-3] Implement dev module

### Description

Create `core/deps/dev.py` with framework developer tool checks:
- Mutation testing: mutmut, stryker, cargo-mutants, mull-runner
- (Future: test runners like pytest, linters like ruff if added)

Does NOT check project-runtime tools (pylsp, clangd, etc.).

### Affected files

- `core/deps/dev.py` — NEW (60 LOC)
  - `check_dev() -> int` function
  - Uses shared `_check()` from `core/deps/__init__.py`

### Expected tests

- `tests/test_install_deps.py::test_dev_mode` — AC-3 coverage
- Verify only dev tools checked (not pylsp, clangd, typescript-language-server)

### Notes

Separates framework-dev concerns from project-runtime concerns.

---

## [step-4] Implement project module and refactor install_deps.py dispatcher

### Description

Create `core/deps/project.py` with all project-runtime tool checks (LSP servers, language runtimes, analysis tools, dep-graph tools). This is the existing `install_deps.py` logic minus bootstrap/dev tools.

Refactor `scripts/install_deps.py` into thin CLI dispatcher:
```python
def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    
    if args.bootstrap:
        from core.deps.bootstrap import check_bootstrap
        return check_bootstrap()
    elif args.dev:
        from core.deps.dev import check_dev
        return check_dev()
    else:
        from core.deps.project import check_project
        return check_project(args.strict)
```

### Affected files

- `core/deps/project.py` — NEW (150 LOC)
  - Extracted from current install_deps.py lines 187-327
  - Checks: node, npm, ast-grep, uv, LSP servers (pylsp, typescript-language-server, clangd, rust-analyzer), dep-graph tools (madge, pipdeptree, cargo, cmake), mutation tools
- `scripts/install_deps.py` — REFACTOR (340 LOC → 50 LOC)
  - Becomes thin dispatcher
  - Preserves backward compat: no flags = `check_project(strict=False)`

### Expected tests

- `tests/test_install_deps.py::test_project_mode` — verify all existing tools still checked
- `tests/test_install_deps.py::test_backward_compat` — verify `install_deps.py` without flags behaves as before
- Regression: `tests/smoke.py` + `tests/e2e_pipeline.py` must pass (AC-8)

### Rollback note

If project.py breaks tool detection, revert this commit and restore original install_deps.py (saved as install_deps.py.bak during refactor).

---

## [step-5] Implement detect_languages skill and klc setup command

### Description

Create `core/skills/detect_languages.py`:
- Read `.klc/index/inventory.json` → count files per extension
- Read `config/profile.yml` → check `languages` field
- Return set of detected languages (threshold: ≥10 files OR explicit in profile.yml)
- Mapping: `.py` → python, `.cpp/.h` → cpp, `.ts/.tsx` → typescript, `.js/.jsx` → javascript, `.rs` → rust

Create `core/phases/setup.py`:
- Call `detect_languages.py` to get language set
- Compute required/optional tools per language (using tool registry from spec.md)
- Print manual install commands
- Write `.klc/index/project-deps.json` with structure from AC-5

Register `setup` subcommand in `scripts/klc`.

### Affected files

- `core/skills/detect_languages.py` — NEW (60 LOC)
  - `detect() -> set[str]` function
- `core/phases/setup.py` — NEW (120 LOC)
  - `run(argv) -> int` function
  - Tool registry: `TOOLS_BY_LANG` dict
- `scripts/klc` — MODIFY (2 LOC added)
  - Add `"setup"` to `OPERATIONAL_CMDS` tuple

### Expected tests

- `tests/test_detect_languages.py::test_detect_from_inventory` — AC-4 coverage
- `tests/test_detect_languages.py::test_profile_override` — profile.yml overrides inventory
- `tests/test_setup_command.py::test_klc_setup` — AC-5 coverage, verify project-deps.json created

### Notes

Core functionality for project-specific tool detection. Satisfies AC-4 and AC-5.

---

## [step-6] Extend klc doctor with project-tool validation

### Description

Add new check function `@check("project-tools")` in `core/phases/doctor.py`:
- Read `.klc/index/project-deps.json` if it exists
- Check required tools from `detected` field
- Return errors list (missing tools)

Update `run()` function to handle `--strict` flag:
- Parse `--strict` from argv
- If `--strict` and project-tools check fails → exit 1
- If no `--strict` → print project-tools errors as warnings, exit 0

### Affected files

- `core/phases/doctor.py` — MODIFY (+40 LOC)
  - Add `@check("project-tools")` function
  - Update `run()` to parse `--strict` flag and conditionally fail

### Expected tests

- `tests/test_doctor.py::test_doctor_strict_mode` — AC-6 coverage
- `tests/test_doctor.py::test_doctor_project_tools_missing_json` — graceful skip if project-deps.json absent
- Regression: existing 9 checks must still pass

### Notes

Satisfies AC-6. Backward compatible: `--strict` is opt-in.

---

## [step-7] Update init.py output and README.md

### Description

Update `scripts/init.py`:
- In `_finalize()` function, add final output hint: "Next steps: 1. klc setup  2. klc doctor"
- Both `--scan-only` and `--finalize` modes print this hint

Update `README.md` install section with 3-phase flow:
```markdown
## Installation

1. Bootstrap framework dependencies:
   ```bash
   python scripts/install_deps.py --bootstrap
   ```

2. Install framework into your project:
   ```bash
   python scripts/klc install <project-root>
   ```

3. Initialize project:
   ```bash
   cd <project-root>
   .klc/bin/klc init --scan-only
   ```

4. Detect language-specific tools:
   ```bash
   .klc/bin/klc setup
   ```

5. Manually install printed tool commands (from step 4 output)

6. Verify installation:
   ```bash
   .klc/bin/klc doctor
   ```
   
   For CI use (fails on missing tools):
   ```bash
   .klc/bin/klc doctor --strict
   ```
```

### Affected files

- `scripts/init.py` — MODIFY (+5 LOC in `_finalize()`)
- `README.md` — MODIFY (~30 lines in install section)

### Expected tests

- `tests/test_init_output.py::test_init_hints_setup` — AC-7 coverage
- Manual checklist item: verify README.md reflects 3-phase flow (AC-9)

### Notes

Documentation and UX improvements. Satisfies AC-7 and AC-9.

---

## Dependencies

Linear dependency chain:
1. step-1 (foundation) → step-2, step-3, step-4 (modules use shared utilities)
2. step-4 (dispatcher) → step-5 (setup command can call project.py if needed)
3. step-5 (setup creates project-deps.json) → step-6 (doctor reads it)
4. step-6 (doctor ready) → step-7 (update docs to reference new commands)

No circular dependencies. Each step builds on previous.

---

## Rollback strategy

- Steps 1-3: safe to revert individually (no user-facing changes).
- Step 4: if breaks, revert and restore original install_deps.py (keep .bak file).
- Steps 5-7: safe to revert individually (new commands, no existing behavior changed).

---

## YAGNI validation

✅ All steps directly implement ACs — no unnecessary abstractions.
✅ No new external dependencies (all tools already in existing install_deps.py).
✅ No future-proofing beyond KLC-004/005 coordination (extension points documented in code comments).
✅ 7 steps is reasonable for M-track refactor (not over-engineered).

---

## Test coverage summary

| AC   | Test location | Step |
|------|---------------|------|
| AC-1 | tests/test_install_deps.py::test_bootstrap_mode | step-2 |
| AC-2 | Manual verification (--project removed) | step-4 |
| AC-3 | tests/test_install_deps.py::test_dev_mode | step-3 |
| AC-4 | tests/test_detect_languages.py::test_detect_from_inventory | step-5 |
| AC-5 | tests/test_setup_command.py::test_klc_setup | step-5 |
| AC-6 | tests/test_doctor.py::test_doctor_strict_mode | step-6 |
| AC-7 | tests/test_init_output.py::test_init_hints_setup | step-7 |
| AC-8 | tests/smoke.py + tests/e2e_pipeline.py (regression) | step-4 |
| AC-9 | Manual verification (README.md) | step-7 |

All ACs covered. Manual checklist items span steps 2-7.
