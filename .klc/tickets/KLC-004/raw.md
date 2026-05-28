---
ticket: KLC-004
kind_hint: feature
created: 2026-05-28T10:48:56Z
---
# KLC-004 — C++ call graph for CMake projects (Phase 4.3)

## Context

Phase 4.3 (optional): extend call graph support to C++ projects using scip-clang (Sourcegraph's LLVM-based indexer).

Python (Phase 4.1) and Rust (Phase 4.2) call graphs are complete. C++ is next optional language.

## Problem

C++ projects lack call graph → review and feature work use whole-file context instead of symbol-level slicing.

C++ has complexities:
- Virtual methods with multiple overrides
- Template instantiations
- Header-only libraries
- Preprocessor macros

Pattern-based parsing insufficient (same issue as Rust). Need compiler-grade analysis.

## Proposed solution

Use **scip-clang** (Sourcegraph's LLVM-based C++ indexer):
- Input: `compile_commands.json` from CMake
- Output: SCIP index → translate to our JSON schema

**Pre-flight checks** (before implementation):
- Target repo uses CMake?
- Can enable `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`?
- Windows users: WSL2 available or plan to run indexing in CI?

**Deliverables**:
- `core/skills/callgraph_cpp.py` — CLI: `--compdb <path> --out <path>`
- Runs `scip-clang`, translates SCIP protobuf → `index/callgraph/cpp.json`
- Virtual method overrides resolved to all known impls
- Header symbols attributed to .cpp where defined
- Decision: vendor scip-clang binary (~150MB) or download-on-first-run

**Integration**:
- Add `cpp` to `profiles/generic/manifest.yml` `enabled_languages`
- context-loader and review.py automatically use C++ graph when available

## Acceptance criteria

- AC-1: Given CMake project with `compile_commands.json`, generates C++ call graph
- AC-2: Virtual method overrides resolve to all implementations
- AC-3: Header-only function correctly attributed to source file
- AC-4: Runtime reasonable on 100k-LOC C++ project (scip-clang is bottleneck, not us)
- AC-5: Clear error when scip-clang not found, with install instructions

## Out of scope

- UE-specific projects (Phase 4.3-bis, separate ticket)
- MSBuild/.vcxproj without CMake (not supported, migration recommended)
- Cross-crate analysis (workspace-only like Rust)

## Platform considerations

**Windows**:
- scip-clang has no native Windows build
- Options: (1) run indexing in WSL2, (2) run in CI on Linux, (3) skip C++
- Indexing is per-PR operation, not hot loop → acceptable

**Linux/macOS**: native scip-clang builds available

## Estimate

- Complexity: 3 (SCIP protobuf format, LLVM semantics, cross-platform)
- Uncertainty: 2 (scip-clang behavior on large projects unknown)
- Risk: 1 (binary dependency, WSL requirement on Windows)
- Manual: 1 (test on real CMake project)
- Total: 7
- Track: S (or M if significant issues)

## Confirmation gate

**Before starting implementation**, confirm:
1. C++ call graph is needed (Python + Rust may be sufficient for current projects)
2. scip-clang dependency acceptable (~150MB binary, vendor or download decision)
3. Windows users can use WSL2 or CI for indexing

User answers: proceed / skip / defer

## Related

- PHASE4_PLAN.md lines 89-122: Phase 4.3 detailed plan
- Phase 4.1 (complete): Python call graph
- Phase 4.2 (KLC-001, complete): Rust call graph
- Phase 4.3-bis (future): UE-specific C++
