# Phase 4 Plan — Function-level call graph integration

## Goals

1. **Quality**: per-symbol context (callers/callees) for review and feature work — fewer hallucinations, better impact analysis.
2. **Cost**: ~5x token reduction by replacing whole-file context with symbol-level BFS over the call graph.

## Scope policy

- **Default tracks (proceed without further confirmation)**: Python (4.1), Rust (4.2), context-loader integration (4.5), review.py integration (4.6).
- **Optional tracks (require explicit user confirmation before starting)**: C++ for CMake projects (4.3), TypeScript (4.4), C++ for UE projects (4.3-bis).
- Integration phases (4.5, 4.6) work with whatever languages have completed call-graph builders.

## Profile assumptions

- **CMake is the universal build system for C++ projects** — `compile_commands.json` is always available via `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`.
- **UE C++ projects are rare** and out of priority — handled separately in 4.3-bis.
- **Visual Studio without CMake** is not supported — recommendation is to use VS's CMake generator.
- **scip-clang has no native Windows build** — Windows users run indexing through WSL or CI. Indexing is a batch operation (per-PR), not a hot loop, so this is acceptable.

## Profile manifest changes (`profiles/*/manifest.yml`)

Each profile gains a `callgraph` section:

```yaml
callgraph:
  enabled_languages: [python, rust]   # languages whose indices are loaded
  index_dir: index/callgraph          # where <lang>.json files live
  honor_excludes: true                # respect profile excludes during scan
```

- `profiles/generic/manifest.yml`: `enabled_languages: [python, rust]` initially. Adds `cpp` after 4.3 confirmation, `typescript` after 4.4 confirmation.
- `profiles/ue/manifest.yml`: `enabled_languages: []` until 4.3-bis is requested.

---

## Phase 4.1 — Python call graph (DEFAULT)

**Approach**: DIY using stdlib `ast` module. No external dependencies.

**Deliverables**:
- `core/skills/callgraph_python.py` — CLI: `--root <path> --out <path> [--module <name>]`
- Output format: `index/callgraph/python.json`
  ```json
  {
    "symbols": {
      "src/api/users.py::create_user": {
        "kind": "function",
        "file": "src/api/users.py",
        "line": 42,
        "calls": ["src/db/users.py::insert", "src/auth/jwt.py::sign"],
        "called_by": ["src/api/routes.py::register_routes"]
      }
    }
  }
  ```
- Resolution: import-aware (follow `from X import Y`, alias tracking), class methods qualified by class name.
- Limitations documented: dynamic dispatch, `getattr`, decorators that wrap calls — best-effort only.

**Acceptance**:
- Builds graph for klc's own `scripts/` and `core/skills/` directories without errors.
- Round-trip test: known caller/callee pair from real code present in output.
- Runtime under 10s on 50k-LOC Python repo.

**Estimate**: 1.5 days

---

## Phase 4.2 — Rust call graph (DEFAULT)

**Approach**: rust-analyzer LSP integration. rust-analyzer exposes call hierarchy via standard LSP methods; we wrap it.

**Deliverables**:
- `core/skills/callgraph_rust.py` — CLI: `--root <path> --out <path>`
- Spawns rust-analyzer in headless mode, queries `textDocument/prepareCallHierarchy` + `callHierarchy/incomingCalls` + `callHierarchy/outgoingCalls` for every function symbol.
- Output format: same schema as Python (`index/callgraph/rust.json`).
- Detects rust-analyzer binary via `$RUST_ANALYZER` env, then `which rust-analyzer`, then fail with clear error.
- Trait method resolution: includes both trait definition and known impls.

**Acceptance**:
- Builds graph for a representative Rust workspace (a crate with `lib.rs` + 5+ modules).
- Trait dispatch resolved to all visible impls.
- Build under 30s on a 100k-LOC workspace (rust-analyzer is the bottleneck, not us).

**Estimate**: 2 days

---

## Phase 4.3 — C++ call graph for CMake projects (OPTIONAL — confirm before starting)

**Approach**: scip-clang (Sourcegraph's compiler-grade C++ indexer, LLVM-based).

**Why optional**:
- WSL dependency on Windows (no native Windows build of scip-clang).
- ~150MB tool dependency — needs a vendor/download decision.

**Pre-flight checks** (run before user confirms):
- Does the target repo build with CMake?
- Can `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` be enabled?
- For Windows users: WSL2 available, or CI Linux runner planned for indexing?

**Deliverables (only after user confirmation)**:
- `core/skills/callgraph_cpp.py` — CLI: `--compdb <path> --out <path>`
- Runs `scip-clang --compdb compile_commands.json -o index.scip`, then translates SCIP protobuf → our JSON schema.
- Decision pending: vendor scip-clang vs. download-on-first-run (resolve at start of 4.3).
- Output: `index/callgraph/cpp.json`.
- After completion, `profiles/generic/manifest.yml` adds `cpp` to `enabled_languages`.

**Out of scope for 4.3**:
- UE-specific compile_commands.json generation (handled in 4.3-bis).
- MSBuild/.vcxproj projects without CMake — explicit "not supported" with migration recommendation.

**Acceptance**:
- Builds graph for a CMake-based C++ project with `compile_commands.json`.
- Virtual method overrides resolved to all known impls.
- Header symbols correctly attributed to the .cpp where defined.

**Estimate (after confirmation)**: 2 days

**Confirmation gate**: at start of 4.3, I will ask:
> "Phase 4.3 (C++ call graph for CMake projects via scip-clang) requires a ~150MB tool and WSL on Windows for local indexing (CI works natively). Proceed, skip, or defer?"

---

## Phase 4.3-bis — C++ call graph for UE projects (OPTIONAL, deferred)

**Approach**: same scip-clang core as 4.3, plus UE-specific compile_commands.json generation via `UnrealBuildTool -mode=GenerateClangDatabase`, plus respecting `profiles/ue/manifest.yml` excludes (Binaries, Intermediate, Saved, DerivedDataCache, Content, Platforms, ThirdParty).

**Status**: deferred until explicitly requested. UE projects are not in the priority set.

**Estimate (after confirmation)**: 1 day on top of 4.3 (4.3 must be done first).

---

## Phase 4.4 — TypeScript call graph (OPTIONAL — confirm before starting)

**Approach**: TypeScript Compiler API (the official `typescript` npm package's programmatic interface).

**Why optional**: requires Node.js + `tsc` in the target repo; works best with a `tsconfig.json`. Smaller fraction of klc's typical projects, so deferring keeps focus.

**Pre-flight checks**:
- `tsconfig.json` present in target repo?
- Node.js ≥ 18 available?

**Deliverables (only after user confirmation)**:
- `core/skills/callgraph_typescript.js` — Node script using `ts.createProgram` and the type checker's `getSymbolAtLocation` to resolve calls.
- `core/skills/callgraph_typescript.py` — Python wrapper that invokes the Node script.
- Output: `index/callgraph/typescript.json`.
- Handles: class methods, arrow functions, default exports, re-exports, async/await chains.
- After completion, `profiles/generic/manifest.yml` adds `typescript` to `enabled_languages`.

**Acceptance**:
- Builds graph for a sample TS project with `tsconfig.json`.
- Re-exports resolved (find original definition, not the re-export site).
- Runtime under 20s on a 50k-LOC TS project.

**Estimate (after confirmation)**: 2.5 days

**Confirmation gate**: at start of 4.4, I will ask:
> "Phase 4.4 (TypeScript call graph via TS Compiler API) requires Node.js and tsconfig.json. Proceed, skip, or defer?"

---

## Phase 4.5 — context-loader integration (DEFAULT)

**Approach**: extend `core/skills/context-loader.py` to optionally load call-graph slices.

**Deliverables**:
- New flag: `--symbol <file::name> --depth <N>` (default 1).
- Reads `callgraph.enabled_languages` from the active profile manifest, loads only those `index/callgraph/<lang>.json` files.
- Performs BFS over `calls` + `called_by` to depth N.
- Outputs context bundle containing only the file ranges holding involved symbols (not whole files).
- Falls back to whole-file context if call graph for the language is missing or `enabled_languages` is empty.
- Logs which files were skipped because of graph slicing (for debugging).

**Acceptance**:
- Token count for a typical review context drops ≥3x on a representative diff (measured before/after).
- Fallback path works when call graph absent (e.g., user skipped 4.3).
- Profile manifest `enabled_languages` is honored — disabled languages get whole-file fallback.

**Estimate**: 1 day

---

## Phase 4.6 — review.py integration (DEFAULT)

**Approach**: feed call-graph slices into review sub-agents that benefit most.

**Deliverables**:
- For changed symbols in diff, compute their callers/callees via call graph.
- Pass `callgraph_slice` field in job cards to: `architecture` (impact analysis), `test-coverage` (find untested callers), `security` (taint paths from sentinels to entry points).
- Update sub-agent prompts to use this slice.
- Template addition: `## Call-graph impact` section in review report listing affected symbols beyond the diff.

**Acceptance**:
- Architecture reviewer flags "function X is called by Y, Z which were not modified — verify behavior".
- Security reviewer can trace from sentinel match back to nearest HTTP handler / entry point.
- Test-coverage reviewer flags untested callers of modified functions.

**Estimate**: 1.5 days

---

## Summary of effort

| Phase | Track | Estimate | Status |
|-------|-------|----------|--------|
| 4.1 Python | DEFAULT | 1.5d | Proceed |
| 4.2 Rust | DEFAULT | 2d | Proceed |
| 4.3 C++ (CMake) | OPTIONAL | 2d | **Awaits confirmation** |
| 4.3-bis C++ (UE) | OPTIONAL, deferred | +1d | On request only |
| 4.4 TypeScript | OPTIONAL | 2.5d | **Awaits confirmation** |
| 4.5 context-loader | DEFAULT | 1d | Proceed |
| 4.6 review.py | DEFAULT | 1.5d | Proceed |

**Default-only path**: ~6 days.
**With C++ (CMake) confirmed**: ~8 days.
**With C++ (CMake) + TypeScript confirmed**: ~10.5 days.

## Order of execution

1. **4.1 Python** — smallest, validates the JSON schema.
2. **4.2 Rust** — proves LSP-based approach.
3. **4.5 context-loader** — unblocks token-cost measurement on Python+Rust.
4. **4.6 review.py** — unblocks quality measurement.
5. **Confirmation gate** for 4.3 (and/or 4.4) — at this point we have data on whether call graphs actually deliver the cost reduction; user decides whether to extend.
6. **4.3 C++ (CMake)** if confirmed.
7. **4.4 TypeScript** if confirmed.
8. **4.3-bis C++ (UE)** only on explicit request.

This ordering means we get measurable results from Python+Rust before investing in the harder C++/TS tracks.
