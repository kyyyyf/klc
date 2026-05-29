---
ticket: KLC-010
kind: tech
authority: human
last_generated: 2026-05-28T15:50:00Z
---

# KLC-010 — Layered dependency installation (bootstrap + project setup)

## Goals

Refactor dependency installation to separate **bootstrap** (minimal tools for `klc init`), **project setup** (language-specific tools after detection), and **dev** (framework contributor tools). Eliminate false-positive `klc doctor` failures for tools the project doesn't use. Provide users with explicit, manual install commands rather than auto-installing everything.

## Problem / Context

> [!FACT F-001] src=scripts/install_deps.py:1-342 verified=2026-05-28
> Current `install_deps.py` checks every tool the framework *could* use across all languages (git, jq, node, npm, ast-grep, uv, pylsp, typescript-language-server, clangd, rust-analyzer, madge, pipdeptree, cargo, cmake, mutmut, stryker, cargo-mutants, mull-runner, jinja2) and reports missing ones.

> [!FACT F-002] src=scripts/install_deps.py:172-175 verified=2026-05-28
> The script has a `--strict` flag, but it's not used differently — all missing tools are always reported as errors (exit 1).

> [!FACT F-003] src=core/phases/install.py:1-80 verified=2026-05-28
> `klc install` bootstraps a project by copying config seeds and creating .klc/ structure. It does NOT call install_deps.py.

> [!FACT F-004] src=scripts/init.py:1-215 verified=2026-05-28
> `klc init` runs file_scanner.py (structural scan) and dep_graph.py (dependency graph), then optionally three LLM agents (inventory/decompose/docgen). Language detection happens during inventory phase.

> [!FACT F-005] src=core/phases/doctor.py:216-240 verified=2026-05-28
> `klc doctor` runs 9 checks (skills-executable, phase-scripts-executable, templates-parse, profile-manifest, reviewer-allowlist, git-available, klc-dispatcher, jira-sync-queue, config-validation). It does NOT check project-specific language tools currently.

Problems:
1. **No layering**: install_deps.py runs independently of project state. User must install ~20 tools upfront regardless of their project's actual needs.
2. **No project-specific validation**: `klc doctor` checks framework health, but not "does this project have the tools it needs?".
3. **False positives**: A pure Python project gets warned about missing clangd/rust-analyzer/typescript-language-server.
4. **Dev vs project confusion**: Framework contributors need test runners, linters against klc itself — but that's mixed with project-runtime tools.

## Acceptance Criteria

1. **AC-1**: `install_deps.py --bootstrap` exits 0 if Python 3.11+, git, and jinja2 are present. Total checks ≤3. No node, npm, ast-grep, uv, or LSP servers checked in bootstrap mode.

2. **AC-2**: `install_deps.py --project` mode is removed. Project-specific tool installation is handled by new `klc setup` command.

3. **AC-3**: `install_deps.py --dev` installs/checks framework dev tools only (mutation testing tools, test runners for klc itself). Does NOT check project-runtime tools like clangd or pylsp.

4. **AC-4**: New skill `core/skills/detect_languages.py` reads `.klc/index/inventory.json` and `config/profile.yml`, returns set of languages detected in the project (e.g., `{"python", "cpp", "typescript"}`).

5. **AC-5**: New command `klc setup` (implemented as `core/phases/setup.py`):
   - Detects languages via detect_languages.py
   - Computes required tools per language (Python → uv, pylsp, ruff; C++ → clangd, scip-clang; TS → typescript-language-server, tsc; Rust → rust-analyzer, cargo)
   - **Prints manual install commands** (does not auto-install)
   - Writes `.klc/index/project-deps.json` with structure:
     ```json
     {
       "languages": ["python", "cpp"],
       "required": {
         "python": ["uv", "pylsp"],
         "cpp": ["clangd"]
       },
       "optional": {
         "python": ["mutmut"],
         "cpp": ["mull-runner"]
       },
       "detected": {
         "uv": "/usr/local/bin/uv",
         "pylsp": null,
         "clangd": "/usr/bin/clangd",
         "mutmut": null
       }
     }
     ```

6. **AC-6**: `klc doctor` gains optional `--strict` flag. Behavior:
   - Default (no `--strict`): reads `.klc/index/project-deps.json` if it exists. Missing required tools → WARN. Optional tools not checked. Exit 0.
   - `--strict`: Missing required tools → FAIL. Exit 1.
   - If `project-deps.json` does not exist, skip project-tool checks and print hint: "Run `klc setup` to detect required tools."

7. **AC-7**: `klc init` final output (both `--scan-only` and `--finalize` modes) includes:
   ```
   Next steps:
     1. klc setup    # detect languages, show required tool install commands
     2. klc doctor   # verify installation health
   ```

8. **AC-8**: `tests/smoke.py` and `tests/e2e_pipeline.py` pass unchanged (framework self-tests still work).

9. **AC-9**: `README.md` install section updated with 3-phase flow:
   ```
   1. python scripts/install_deps.py --bootstrap
   2. klc install <project>
   3. cd <project> && .klc/bin/klc init --scan-only
   4. .klc/bin/klc setup
   5. (manually run printed install commands)
   6. .klc/bin/klc doctor
   ```

## Non-goals

- Auto-installing project tools (user explicitly chose manual install).
- Per-OS package manager abstraction (keep existing heuristics in install_deps.py).
- Replacing language detection logic (reuse what inventory.json already captures).
- Adding tool version constraints (e.g., "Python 3.11+ but <3.13"). Scope: presence/absence only.
- Migrating existing `.klc/config/tools.json` format (resolved tools registry unchanged).

## Constraints

> [!CONSTRAINT C-001] source=KLC-008 (e2e tests as safety net)
> All changes must pass `tests/smoke.py` and `tests/e2e_pipeline.py`. These cover XS/S/M/L track phase loops and protect against regressions.

> [!CONSTRAINT C-002] source=user decision (2026-05-28)
> Manual install only — `klc setup` prints commands, does not execute them. No `--auto-install` mode.

> [!CONSTRAINT C-003] source=user decision (2026-05-28)
> `.klc/index/project-deps.json` is auto-generated (like inventory.json, depgraph.json) and not committed to git. Regenerated on every `klc setup` run.

> [!CONSTRAINT C-004] source=F-005
> `klc doctor` currently has 9 checks. New project-tool validation must be added as check #10 (or integrated into existing checks) without breaking the 9 existing ones.

## Affected modules

- **scripts/install_deps.py**: refactor into `--bootstrap`, `--project` (deprecated/removed), `--dev` modes
- **core/phases/doctor.py**: add project-tool validation check that reads `.klc/index/project-deps.json`
- **scripts/init.py**: update final output to hint "Next: run `klc setup`"
- **core/skills/** (new): `detect_languages.py` — language detection skill
- **core/phases/** (new): `setup.py` — new command for project setup
- **scripts/klc** (dispatcher): register `setup` subcommand
- **README.md**: update install instructions

## Open questions

> [!QUESTION Q-001] blocks=design
> For language detection, should we read inventory.json's `file_count` per extension, or also check profile.yml's `languages` field? Proposal: check both — inventory.json for detected files, profile.yml for user-declared overrides (e.g., a C++ project with embedded Python scripts may set `languages: ["cpp"]` to skip Python tool checks).

> [!QUESTION Q-002] blocks=design
> What is the threshold for detecting a language? Proposal: ≥10 files of that extension in inventory.json, OR language explicitly listed in profile.yml. Edge case: a repo with 3 .py files for build scripts should not require pylsp.

> [!QUESTION Q-003] blocks=design
> Should `klc doctor --strict` be the default in CI environments (detected via CI=true env var), or always require explicit `--strict` flag? Proposal: always explicit flag — makes CI configs self-documenting.

> [!QUESTION Q-004] blocks=acceptance-test-plan
> KLC-004 (C++ call graph) and KLC-005 (TS call graph) are not yet implemented. How do we test that they can register their tools (scip-clang, tsc) through the new mechanism? Proposal: leave hooks in `detect_languages.py` for future tools, document the extension point in code comments.

## Estimate

Scoring on four axes (0-3 each):

- **Complexity**: 3 (new command + skill + refactor existing installer + integrate with doctor + update 3 scripts)
- **Uncertainty**: 2 (interaction with KLC-004/005 tools unknown; language detection thresholds need validation; unclear if profile.yml overrides are needed)
- **Risk**: 1 (regression in install flow blocks new users, but KLC-008 e2e tests provide safety net; no data loss risk)
- **Manual**: 1 (test on clean checkout; verify bootstrap → init → setup → doctor flow; smoke + e2e cover framework self-test)

**Total**: 7

**Track**: M (full lifecycle — 7 points + complexity=3 floors at M)

## Related tickets

- **KLC-008** (E2E tests): provides safety net for refactor. Completed 2026-05-28.
- **KLC-004** (C++ call graph): will add scip-clang to project deps. Not started.
- **KLC-005** (TS call graph): will add tsc to project deps. Not started.
- **KLC-003** (publish adapters): independent. Can run in parallel or before KLC-010.
- **KLC-009** (config cleanup): completed 2026-05-28. No conflict (009 touched config/, 010 touches scripts/ and core/).

## Implementation notes

### Language detection logic (AC-4)

Proposed `detect_languages.py` behavior:
1. Read `.klc/index/inventory.json` → count files per extension.
2. Read `config/profile.yml` → check if `languages` field exists.
3. Return union of:
   - Languages with ≥10 files in inventory.json
   - Languages explicitly listed in profile.yml

Mapping (extensible for KLC-004/005):
- `.py` → `python`
- `.cpp`, `.cc`, `.cxx`, `.hpp`, `.h` → `cpp`
- `.ts`, `.tsx` → `typescript`
- `.js`, `.jsx` → `javascript`
- `.rs` → `rust`

### Tool registry (AC-5)

Per-language tool mapping:
- `python`: required=[uv, pylsp], optional=[mutmut, pipdeptree]
- `cpp`: required=[clangd], optional=[scip-clang (KLC-004), mull-runner]
- `typescript`: required=[typescript-language-server, tsc], optional=[stryker]
- `javascript`: required=[node, npm], optional=[madge, stryker]
- `rust`: required=[rust-analyzer, cargo], optional=[cargo-mutants]

### Bootstrap vs dev tools (AC-1, AC-3)

**Bootstrap** (`--bootstrap`):
- Python 3.11+ (sys.version_info check)
- git (shutil.which)
- jinja2 (importlib check)

**Dev** (`--dev`):
- mutation testing tools: mutmut, stryker, cargo-mutants, mull-runner
- test runners for klc itself (pytest, if added)
- linters (ruff, mypy, if added)

**Project tools** (via `klc setup`, not install_deps.py):
- LSP servers: pylsp, clangd, typescript-language-server, rust-analyzer
- Language runtimes: node, npm, cargo
- Analysis tools: uv, ast-grep, madge, pipdeptree, cmake

### `klc setup` output format (AC-5)

Example output:
```
[setup] Detected languages: python, cpp
[setup] Required tools:
  python:
    - uv         (missing) — install: curl -LsSf https://astral.sh/uv/install.sh | sh
    - pylsp      (missing) — install: uv tool install python-lsp-server
  cpp:
    - clangd     (found: /usr/bin/clangd)

[setup] Optional tools (not required for basic functionality):
  python:
    - mutmut    (missing) — install: pipx install mutmut
  cpp:
    - scip-clang (missing) — install: (see KLC-004 for instructions)

[setup] Wrote .klc/index/project-deps.json

Next: install missing tools, then run `klc doctor` to verify.
```

### `klc doctor` integration (AC-6)

Add new check function in `core/phases/doctor.py`:

```python
@check("project-tools")
def _project_tools() -> list[str]:
    """Check project-specific language tools."""
    errs: list[str] = []
    deps_file = klc_index_dir() / "project-deps.json"
    if not deps_file.exists():
        # Not an error — just skip check
        return []
    
    import json
    deps = json.loads(deps_file.read_text())
    
    # Check required tools only (optional tools ignored)
    for lang, tools in deps.get("required", {}).items():
        for tool in tools:
            detected = deps.get("detected", {}).get(tool)
            if detected is None:
                errs.append(f"{tool} (required for {lang}) — not found")
    
    return errs
```

In `run()` function, check for `--strict` arg:
- If `--strict` and `_project_tools()` returns errors → overall_ok = False (exit 1)
- If no `--strict` → print errors as warnings but don't fail (exit 0)

### Migration path for existing users

No migration needed — `.klc/index/project-deps.json` does not exist yet. First `klc setup` run creates it. Existing `install_deps.py` without flags continues to work (backward compat), but documentation recommends new flow.

## Design decisions (user-confirmed 2026-05-28)

1. **Auto-install level**: Manual only — `klc setup` prints commands, does not execute.
2. **`klc doctor` strictness**: Configurable via `--strict` flag. Default: WARN. With `--strict`: FAIL.
3. **Manifest location**: `.klc/index/project-deps.json` (auto-generated, not committed).
4. **Dev vs runtime**: Separate `--dev` mode in install_deps.py for framework contributors.
