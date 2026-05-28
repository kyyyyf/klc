---
ticket: KLC-001
phase: build
authority: agent
last_updated: 2026-05-28T12:59:00Z
---

# Implementation plan — KLC-001

Async LSP-based Rust call graph integration via rust-analyzer.

## Steps

- [x] **step-1**: AsyncLSPClient class with asyncio subprocess + background reader
  - Replace sync subprocess with `asyncio.create_subprocess_exec`
  - Implement `_read_loop()` background task for LSP messages
  - Parse Content-Length headers + JSON bodies
  - Dispatch responses to futures, notifications to handlers
  - **Affected files**: `core/skills/callgraph_rust_async.py` (new)
  - **Tests**: `tests/test_callgraph_rust_lsp.py::test_basic_edges`

- [x] **step-2**: $/progress notification tracking + indexing wait
  - Handle `$/progress` notifications in `_read_loop()`
  - Set `indexing_done` event when workDone completes
  - Add timeout (30s) in `initialize()`
  - **Affected files**: `core/skills/callgraph_rust_async.py`
  - **Tests**: `tests/test_callgraph_rust_lsp.py::test_basic_edges`

- [x] **step-3**: Document symbol extraction + function filtering
  - Implement `textDocument/documentSymbol` request
  - Extract function/method symbols (SymbolKind 12, 6)
  - Build qualified names from file path + symbol hierarchy
  - **Affected files**: `core/skills/callgraph_rust_async.py`
  - **Tests**: `tests/test_callgraph_rust_lsp.py::test_basic_edges`

- [x] **step-4**: Call hierarchy integration (outgoing + incoming calls)
  - Implement `textDocument/prepareCallHierarchy`
  - Implement `callHierarchy/outgoingCalls` (callees)
  - Implement `callHierarchy/incomingCalls` (callers)
  - Build `symbols_map` with calls/called_by edges
  - **Affected files**: `core/skills/callgraph_rust_async.py`
  - **Tests**: `tests/test_callgraph_rust_lsp.py::test_basic_edges`

- [x] **step-5**: Full call graph builder + output formatting
  - Iterate all .rs files (exclude target/)
  - For each file: didOpen → documentSymbol → prepareCallHierarchy → outgoingCalls + incomingCalls
  - Output same JSON schema as pattern version
  - **Affected files**: `core/skills/callgraph_rust_async.py`
  - **Tests**: `tests/test_callgraph_rust_lsp.py::test_basic_edges` (AC-1) ✓

- [x] **step-6**: Error handling + fallback logic
  - rust-analyzer not found → clear error message (AC-4)
  - Indexing timeout → log warning, proceed with partial results
  - Invalid Rust code → skip file, log warning
  - **Affected files**: `core/skills/callgraph_rust_async.py`
  - **Tests**: `tests/test_callgraph_rust_lsp.py::test_fallback_missing_analyzer` (AC-4) ✓

## Dependencies

- rust-analyzer in $PATH or $RUST_ANALYZER env var
- Cargo workspace (Cargo.toml at root)
- Python 3.7+ (asyncio support)

## Acceptance

All tests in `tests/test_callgraph_rust_lsp.py` pass:
- AC-1: Same edges as pattern version (register_user → auth::hash_password, db::insert_user)
- AC-2: Trait dispatch (stretch goal — verify manually)
- AC-3: Performance < 30s on 100k-LOC workspace
- AC-4: Graceful fallback when rust-analyzer missing

## Notes

Pattern version (`callgraph_rust.py`) provides baseline edges for acceptance testing. Keep it intact until LSP version validated.
