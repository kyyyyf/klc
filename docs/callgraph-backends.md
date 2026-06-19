# Call graph backends

klc uses language-specific LSP backends to produce
`.klc/index/callgraph/<lang>.json` (schema: `{symbols: {id: {kind, file, line, calls, called_by}}}`).
`scripts/review.py` slices the appropriate graph for changed files and
passes it to review agents.

## Language backends

| Language | Backend | Script |
|----------|---------|--------|
| Python | Static AST (ast module) | `core/skills/callgraph_python.py` |
| Rust | rust-analyzer LSP | `core/skills/callgraph_rust_async.py` |
| C++ | **clangd LSP** | `core/skills/callgraph_cpp.py` |

### C++ — clangd (default, KLC-004)

```
callgraph_cpp.py --backend clangd --compdb <path/to/compile_commands.json> --out .klc/index/callgraph/cpp.json
```

**Prerequisites:**
- `clangd` on `$PATH` (or `$CLANGD` env var pointing at the binary).
  Install: <https://clangd.llvm.org/installation>
- `compile_commands.json` in the project root (or passed via `--compdb`).
  Generate with: `cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON <src>`

**Scope:** queries translation units listed in `compile_commands.json` plus
header files found in the project tree (for header-only / inline functions).
Virtual-method overrides are best-effort via `goToImplementation`; full
override resolution is not guaranteed.

**Query mode** (AC-4/D-002): find all references or symbol locations without
loading source into the caller's context:

```
# All call sites of a symbol (file:line JSON array)
callgraph_cpp.py --backend clangd --compdb <path> --query references --symbol hash_password

# All locations of symbols matching a name
callgraph_cpp.py --backend clangd --compdb <path> --query workspace-symbol --symbol insert_user
```

**Future option — scip-clang:** a pre-built on-disk SCIP index (`scip-clang`)
could replace per-run LSP queries for large projects where clangd cold-start
is prohibitively slow. Not implemented; document as a CI/cache option only
when repo-wide sweeps become frequent enough to justify a persistent index.
