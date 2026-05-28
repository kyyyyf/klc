---
ticket: KLC-005
kind_hint: feature
created: 2026-05-28T10:49:22Z
---
# KLC-005 — TypeScript call graph via TS Compiler API (Phase 4.4)

## Context

Phase 4.4 (optional): extend call graph support to TypeScript projects using TypeScript Compiler API.

Python (Phase 4.1) and Rust (Phase 4.2) complete. C++ (Phase 4.3, KLC-004) optional. TypeScript is next optional language.

## Problem

TypeScript projects lack call graph → review and feature work use whole-file context instead of symbol-level slicing.

TypeScript has complexities:
- Class methods, arrow functions, function expressions
- Default exports, re-exports, barrel files
- async/await chains
- Type-only imports vs value imports
- Dynamic `import()` expressions

Need compiler-grade type checker for accurate resolution.

## Proposed solution

Use **TypeScript Compiler API** (official `typescript` npm package):
- Node.js script using `ts.createProgram` and type checker
- Resolve calls via `getSymbolAtLocation` and type information
- Python wrapper to invoke Node script

**Pre-flight checks** (before implementation):
- Target repo has `tsconfig.json`?
- Node.js ≥18 available?
- TypeScript installed in project (`node_modules/typescript`)?

**Deliverables**:
- `core/skills/callgraph_typescript.js` — Node script using TS Compiler API
- `core/skills/callgraph_typescript.py` — Python wrapper, CLI: `--root <path> --out <path>`
- Output: `index/callgraph/typescript.json` (same schema)
- Handles: class methods, arrow functions, default/re-exports, async/await

**Integration**:
- Add `typescript` to `profiles/generic/manifest.yml` `enabled_languages`
- context-loader and review.py automatically use TS graph when available

## Acceptance criteria

- AC-1: Given TS project with `tsconfig.json`, generates TypeScript call graph
- AC-2: Re-exports resolve to original definition (not re-export site)
- AC-3: Arrow functions and class methods correctly tracked
- AC-4: Default exports resolve correctly
- AC-5: Runtime under 20s on 50k-LOC TS project
- AC-6: Clear error when Node.js or tsconfig.json missing

## Out of scope

- JavaScript without types (require TS or JSDoc annotations)
- Dynamic `require()` / `import()` (best-effort only)
- Monorepo project references (single tsconfig.json workspace only)

## Platform considerations

**All platforms**:
- Requires Node.js ≥18 in PATH
- Requires `typescript` npm package in target project
- Works on Windows, Linux, macOS natively

## Estimate

- Complexity: 3 (TS Compiler API, re-export resolution, async patterns)
- Uncertainty: 2 (TS API behavior on large projects unknown)
- Risk: 0 (Node.js widely available, no binary dependencies)
- Manual: 1 (test on real TS project)
- Total: 6
- Track: S

## Confirmation gate

**Before starting implementation**, confirm:
1. TypeScript call graph needed (Python + Rust may be sufficient)
2. Node.js requirement acceptable (most modern projects have it)
3. Target projects have `tsconfig.json` (or willing to add minimal one)

User answers: proceed / skip / defer

## Related

- PHASE4_PLAN.md lines 135-161: Phase 4.4 detailed plan
- Phase 4.1 (complete): Python call graph
- Phase 4.2 (KLC-001, complete): Rust call graph
- Phase 4.3 (KLC-004): C++ call graph (optional)
