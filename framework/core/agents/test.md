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
- `--type feature | bug`
- `framework/config/reviewers.yml` — `test.mutation_score_threshold`
  (default 80); `test.per_language.<lang>.mutation_enabled` can disable
  mutation testing entirely for a language.
- `framework/index/modules.json` — resolves module paths.
- `framework/core/skills/test-writer.py` — produces tests and runs mutation.

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

Persist detection to `framework/index/test-framework.json`:

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

### 3. Derive the test list
From the spec:
- **Happy path** — one test per acceptance criterion.
- **Edge cases** — only those the spec enumerates.
- **Error cases** — each documented failure mode.
- **Boundary values** — where numeric ranges are involved.

For `--type bug` prepend exactly one regression test that currently
fails. Name it so the bug id is searchable.

### 4. Generate
`framework/core/skills/test-writer.py --spec <spec> --modules <list> [--type bug]`.
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
