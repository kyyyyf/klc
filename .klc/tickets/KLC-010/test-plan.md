---
ticket: KLC-010
authority: hybrid
last_generated: 2026-05-29T00:05:00Z
---

# Test plan — KLC-010

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_install_deps.py::test_bootstrap_mode | Verify `install_deps.py --bootstrap` checks ≤3 deps (Python, git, jinja2) |
| AC-2 | manual | Manual verification | Confirm `install_deps.py --project` is removed or deprecated |
| AC-3 | acceptance | tests/test_install_deps.py::test_dev_mode | Verify `install_deps.py --dev` checks only framework dev tools (mutmut, stryker, etc.) |
| AC-4 | unit | tests/test_detect_languages.py::test_detect_from_inventory | Test `detect_languages.py` returns correct language set from inventory.json |
| AC-5 | e2e | tests/test_setup_command.py::test_klc_setup | Run `klc setup` on test repo, verify project-deps.json created and install commands printed |
| AC-6 | acceptance | tests/test_doctor.py::test_doctor_strict_mode | Test `klc doctor` default (WARN) vs `--strict` (FAIL) behavior with missing tools |
| AC-7 | acceptance | tests/test_init_output.py::test_init_hints_setup | Verify `klc init` output includes "Next: run `klc setup`" hint |
| AC-8 | acceptance | tests/smoke.py + tests/e2e_pipeline.py | Regression: existing framework tests pass unchanged |
| AC-9 | manual | Manual verification | Check README.md install section reflects 3-phase flow |

## Edge cases

1. **Empty project (no code files)**: `detect_languages.py` returns empty set; `klc setup` prints "No languages detected, skipping tool setup."

2. **Profile.yml overrides inventory**: User sets `languages: ["cpp"]` in profile.yml but repo has 500 .py files. Respect profile.yml (only check C++ tools).

3. **project-deps.json missing**: `klc doctor` skips project-tool checks and prints hint "Run `klc setup` to detect required tools."

4. **Bootstrap without git**: `install_deps.py --bootstrap` exits 1, prints install instructions for git.

5. **Language detection threshold**: Repo has 5 .py files (build scripts). Should not detect Python as primary language (threshold: ≥10 files or explicit in profile.yml).

6. **Windows clangd auto-detect**: Existing Visual Studio detection logic in install_deps.py (lines 88-133) must work in `--dev` mode, not bootstrap.

7. **Tool already in .klc/config/tools.json**: `klc setup` reads resolved tool paths from tools.json (e.g., clangd on Windows) and marks as detected.

8. **Multiple languages**: Project with Python + C++ + TypeScript. `klc setup` prints install commands for all three language toolchains.

## Regression scenarios

1. **Existing install_deps.py without flags**: Must continue to work (backward compat) — warns about all tools as before, does not break on upgrade.

2. **klc init --scan-only**: Must complete without requiring `klc setup` (setup is optional, only needed if user wants project-specific validation).

3. **klc doctor existing checks**: All 9 existing checks (skills-executable, phase-scripts-executable, templates-parse, profile-manifest, reviewer-allowlist, git-available, klc-dispatcher, jira-sync-queue, config-validation) must pass unchanged.

4. **scripts/klc dispatcher**: Adding `setup` subcommand must not break existing commands (intake, status, next, ack, ship, jump, abort, step, board, doctor, metrics, reindex, install, jira-sync, init, update).

5. **KLC-008 e2e tests**: All 4 track pipelines (XS/S/M/L) must complete successfully with new install flow.

## Manual checklist

- [ ] Run `python scripts/install_deps.py --bootstrap` on clean VM / container with only Python 3.11+ installed. Verify it checks ≤3 dependencies (no node, npm, ast-grep, etc.).

- [ ] Run `klc install <test-project>` + `klc init --scan-only` + `klc setup` on a Python repo. Verify printed install commands include uv, pylsp.

- [ ] Run `klc setup` on a C++ repo. Verify printed install commands include clangd (and optionally scip-clang placeholder).

- [ ] Run `klc setup` on mixed-language repo (Python + TypeScript). Verify commands for both languages printed.

- [ ] Run `klc doctor` without `--strict` on a project with missing tools. Verify output shows WARNings, exit code 0.

- [ ] Run `klc doctor --strict` on same project. Verify output shows FAILs, exit code 1.

- [ ] Run `klc init --scan-only` and verify final output includes "Next steps: 1. klc setup".

- [ ] Verify README.md install section updated with 3-phase flow (bootstrap → install → init → setup → manual install → doctor).

- [ ] Run `tests/smoke.py` and `tests/e2e_pipeline.py` — all tests must pass.

- [ ] Test `install_deps.py --dev` on framework repo itself. Verify it checks mutmut, stryker, cargo-mutants, mull-runner (but not pylsp, clangd, etc.).

## Detailed coverage

| step | Test type | Test name / location | Target symbol(s) | Notes |
|------|-----------|----------------------|------------------|-------|
| step-1 | unit | tests/deps/test_utils.py::test_platform_detection | `core.deps.platform_tag` | Test OS detection returns correct value |
| step-1 | unit | tests/deps/test_utils.py::test_has_tool | `core.deps._has` | Mock shutil.which to test tool presence check |
| step-1 | unit | tests/deps/test_utils.py::test_check_helper | `core.deps._check` | Verify error reporting for missing tools |
| step-2 | unit | tests/deps/test_bootstrap.py::test_python_version | `core.deps.bootstrap.check_bootstrap` | Mock sys.version_info to test Python 3.11+ check |
| step-2 | unit | tests/deps/test_bootstrap.py::test_git_missing | `core.deps.bootstrap.check_bootstrap` | Mock shutil.which to simulate missing git |
| step-2 | unit | tests/deps/test_bootstrap.py::test_jinja2_missing | `core.deps.bootstrap.check_bootstrap` | Mock __import__ to simulate missing jinja2 |
| step-2 | acceptance | tests/test_install_deps.py::test_bootstrap_mode | `scripts.install_deps.main` | Backs AC-1 at the unit layer |
| step-3 | unit | tests/deps/test_dev.py::test_check_dev_tools | `core.deps.dev.check_dev` | Verify only mutation testing tools checked |
| step-3 | acceptance | tests/test_install_deps.py::test_dev_mode | `scripts.install_deps.main` | Backs AC-3 at the unit layer |
| step-4 | unit | tests/deps/test_project.py::test_check_project_all_tools | `core.deps.project.check_project` | Verify all LSP servers, language runtimes checked |
| step-4 | integration | tests/test_install_deps.py::test_backward_compat | `scripts.install_deps.main` | Verify install_deps.py without flags behaves as before (calls check_project) |
| step-4 | characterisation | tests/test_install_deps.py::test_existing_tool_checks | existing install_deps.py behavior | Pin existing tool check behavior before refactor |
| step-4 | acceptance | tests/smoke.py + tests/e2e_pipeline.py | — | Backs AC-8: regression test for framework |
| step-5 | unit | tests/test_detect_languages.py::test_detect_from_inventory | `core.skills.detect_languages.detect` | Backs AC-4 at the unit layer |
| step-5 | unit | tests/test_detect_languages.py::test_profile_override | `core.skills.detect_languages.detect` | Test profile.yml overrides inventory.json |
| step-5 | unit | tests/test_detect_languages.py::test_threshold_check | `core.skills.detect_languages.detect` | Test ≥10 files threshold for language detection |
| step-5 | unit | tests/test_setup_command.py::test_tool_registry | `core.phases.setup.TOOLS_BY_LANG` | Verify tool mapping per language is correct |
| step-5 | integration | tests/test_setup_command.py::test_klc_setup_python_repo | `core.phases.setup.run` | Run setup on mock Python repo, verify project-deps.json structure |
| step-5 | e2e | tests/test_setup_command.py::test_klc_setup | `core.phases.setup.run` | Backs AC-5 at the unit layer |
| step-5 | — | — | `scripts.klc` dispatcher | covered-by: AC-5 (tested via klc setup command) |
| step-6 | unit | tests/test_doctor.py::test_project_tools_check | `core.phases.doctor._project_tools` | Test project-tools check reads project-deps.json correctly |
| step-6 | unit | tests/test_doctor.py::test_project_tools_missing_json | `core.phases.doctor._project_tools` | Test graceful skip when project-deps.json absent |
| step-6 | acceptance | tests/test_doctor.py::test_doctor_strict_mode | `core.phases.doctor.run` | Backs AC-6 at the unit layer |
| step-6 | integration | tests/test_doctor.py::test_doctor_existing_checks | `core.phases.doctor.run` | Verify all 9 existing checks still pass (regression) |
| step-7 | unit | tests/test_init_output.py::test_finalize_output | `scripts.init._finalize` | Test final output includes "klc setup" hint |
| step-7 | acceptance | tests/test_init_output.py::test_init_hints_setup | `scripts.init.main` | Backs AC-7 at the unit layer |
| step-7 | manual | Manual verification | README.md | covered-by: AC-9 |

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
