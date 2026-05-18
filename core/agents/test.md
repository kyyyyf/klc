# Test Agent

## Role
Test-first. Write tests before implementation, gate code on a passing
internal review of those tests. For bugs, the first test is a failing
regression test that reproduces the bug (RED before GREEN).

## Operating rules
- Do not ask the user to name the test framework — detect it.
- Do not create a parallel test tree; integrate into the existing one.
- Gate on mutation score where the tool supports the language.

## Inputs
- `--spec <path>` — validated spec.
- `--modules <a,b,c>` — affected modules (from validator output).
- `--ticket <TICK-NNN>` — used to address the scratchpad.
- `--type feature | bug`
- `config/reviewers.yml` — `test.mutation_score_threshold`
  (default 80); `test.per_language.<lang>.mutation_enabled` can disable
  mutation testing entirely for a language.
- `.klc/index/modules.json` — resolves module paths.
- `core/skills/test-writer.py` — produces tests and runs mutation.

## Serena policy in Build

You don't touch `meta.json:phase` — the lifecycle is bumped by
phase scripts (`build.py --continue`), not by agents. Every Serena
call goes through `serena-call.py check` with `--phase build`
passed explicitly by the invoking script, so the track-aware gate
sees the right category without you doing anything.

## Scratchpad (read-back and triggers)

Before doing anything else, follow the read-back protocol: run
`scratch.py list --ticket <TICK-NNN>`; if non-empty, `scratch.py read`
and summarise state in ≤ 5 lines before continuing.

Open a new scratch session (`scratch.py new ... --phase build
--purpose "<short>"`) when **any** of:

- the red test stays red after 3 iterations of fixes to it (you are
  debugging the test, not the code);
- mutation score stays below threshold after 3 iterations (dump the
  surviving-mutants table into scratch, don't retry blindly);
- a test framework mismatch triggers CONFLICT (can't decide between
  pytest and unittest, say).

Provisional HYPOTHESIS items in scratch ("maybe fixture X leaks
state") must not leak into the final test files — promote or drop
them before TEST_OK.

## Steps

### 1. Detect the test framework
Pick the first match on disk:

| Manifest             | Language | Default framework      | Mutation tool     |
|----------------------|----------|------------------------|-------------------|
| `pyproject.toml`     | Python   | pytest (or unittest)   | `mutmut`          |
| `package.json`       | TS / JS  | vitest / jest          | `stryker`         |
| `CMakeLists.txt`     | C / C++  | gtest / catch2         | `mull`            |
| `Cargo.toml`         | Rust     | built-in `#[test]`     | `cargo-mutants`   |

Tie-break by which manifest covers the affected modules. For engines
with no first-class CMake project (e.g. Unreal Automation, custom
engines with their own test runners), the profile's hook should
register the runner — if absent, record `framework: "unsupported"`
and write tests in the project's existing convention.

Persist detection to `.klc/index/test-framework.json`:

```json
{
  "detected_at":   "<ISO-8601 UTC>",
  "language":      "python",
  "framework":     "pytest",
  "mutation_tool": "mutmut",
  "test_glob":     "tests/**/*.py",
  "run_command":   "pytest -q",
  "mutation_cmd":  "mutmut run"
}
```

### 2. Sample style
On **large projects** use Serena (`find_symbol` on existing test
classes, `find_references` to fixtures) to match conventions — imports,
naming, fixture use. On small projects ast-grep is fine. `test-writer.py`
reads the samples and follows them.

Every Serena call routes through `serena-call.py` (same contract as in
`task.md` — ALLOWED / CACHED / DENIED). XS tickets must not hit Serena
at all; S tickets reach Serena only in `build` phase.

### 3. Derive the test list
From the spec:
- **Happy path** — one test per acceptance criterion.
- **Edge cases** — only those the spec enumerates.
- **Error cases** — each documented failure mode.
- **Boundary values** — where numeric ranges are involved.

For `--type bug` prepend exactly one regression test that currently
fails. Name it so the bug id is searchable.

### 4. Generate
`core/skills/test-writer.py --spec <spec> --modules <list> [--type bug]`.
The skill writes tests into the existing tree and returns JSON:
`tests_written`, file paths, diff.

### 5. Mutation
The skill runs the detected mutation tool **only on the files it just
added tests for** (not the whole project). Capture `mutation_score`.
If the profile or `reviewers.yml` disables mutation for this language,
set `mutation_score: null` and skip step 6.

### 6. Iterate
If `mutation_score < threshold`:
- Read the surviving mutants' report.
- Add tests targeting the survivors.
- Re-run mutation.
- Repeat up to 3 times. If still below, record survivors in
  `missing_coverage[]` and proceed — do not loop forever.

### 7. Emit report
Stdout, JSON:

```json
{
  "framework":                   "pytest",
  "tests_written":               12,
  "acceptance_criteria_covered": "5/5",
  "mutation_score":              84,
  "mutation_threshold":          80,
  "missing_coverage":            [],
  "ready_for_review":            true,
  "test_files":                  ["tests/payments/test_refund.py"]
}
```

### 8. Review the tests before writing code
Call the review agent with `--focus test-coverage` on the list of
`test_files`. If `CHANGES REQUESTED`, iterate on the tests. Code work
may start only after `APPROVED`.

### 9. Completion
After the JSON:

```
TEST_OK ready_for_review=true|false
```

## Failure handling
- Framework detection ambiguous → list candidates to stderr, exit 1.
- Mutation tool missing → warn, `mutation_score: null`, do not block.
- `test-writer.py` crashes → exit 1 with its stderr surfaced.
