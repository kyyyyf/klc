---
name: klc-test
description: klc test phase agent
model: sonnet
---
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
Use LSP (`workspaceSymbol`, `findReferences`) to find existing test
classes and fixtures and match their conventions — imports, naming,
fixture use. For structural pattern matching use ast-grep. `test-writer.py`
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

### 9. Commit the failing tests with the step subject

Before emitting `TEST_OK`, commit the failing tests using the step subject format
so the red-before-green ordering gate can attribute the commit:

```
KLC-NNN step-N: add failing test for <feature>
```

This commit subject convention is required. The `klc ack` gate (`core/skills/tdd_order.py`)
searches git history for commits matching `TICKET step-N` and sanctions the step if no
test-touching commit precedes the implementation commit.

### 10. Completion
After the JSON:

```
TEST_OK ready_for_review=true|false
```

## Failure handling
- Framework detection ambiguous → list candidates to stderr, exit 1.
- Mutation tool missing → warn, `mutation_score: null`, do not block.
- `test-writer.py` crashes → exit 1 with its stderr surfaced.

## Completion signal (orchestrator)

In addition to any phase-specific signal above, end your final output
with exactly one fenced JSON object, as the LAST block in your response:

```json
{"phase":"<phase-id>","signal":"done","artifacts":["path/relative/to/ticket/dir.md"],"blocking_questions":[],"next_action":"ack"}
```

- `phase` — the phase id you were dispatched for (your agent name after
  the `klc-` prefix, e.g. `klc-design` -> `"design"`).
- `signal` — `"done"` | `"blocked"` | `"failed"`.
- `artifacts` — paths you wrote, relative to the ticket directory.
- `blocking_questions` — string[]; leave `[]` if none. Blank/empty
  entries are ignored by the orchestrator.
- `next_action` — `"ack"` | `"clarify"` | `"stop"`.
- Optional: `"tokens":{"in":N,"out":N}`.

This is consumed by the `/klc:run` orchestrator (KLC-052) to decide the
next step without re-reading your artifacts. It does not replace any
phase-specific signal line above — both are expected.
