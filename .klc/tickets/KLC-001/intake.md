# KLC-001: Rust LSP call graph integration

## Problem

Phase 4.2 currently uses pattern-based parsing for Rust call graphs. This approach:
- Misses macro-generated code
- Cannot resolve trait dispatch to impls
- Fails on complex generics
- ~70% accuracy vs compiler-grade analysis

rust-analyzer LSP provides compiler-accurate call hierarchy, but initial integration attempt failed due to:
1. Synchronous LSP client design — rust-analyzer sends notifications interleaved with responses
2. Missing workspace indexing wait — LSP returns empty results before indexing completes
3. No didOpen for files before querying symbols

## Goal

Replace pattern-based `callgraph_rust.py` with production-grade rust-analyzer LSP integration:
- Async IO for notification handling
- Workspace indexing detection (wait for `$/progress` workDone or timeout)
- Proper LSP lifecycle: initialize → wait → didOpen → query → shutdown
- Same JSON output schema as current version

## Success criteria

1. Builds call graph for test workspace (3 .rs files, 6 functions) with same edges as pattern version
2. Handles trait dispatch: resolves trait methods to all visible impls
3. Runtime under 30s on 100k-LOC Rust workspace (rust-analyzer indexing is bottleneck)
4. Falls back gracefully if rust-analyzer not found

## Non-goals

- Generic macro expansion beyond what rust-analyzer provides
- Cross-crate call graph (workspace-only)

## Technical approach

Use Python `asyncio` for LSP protocol:
- `asyncio.create_subprocess_exec` for rust-analyzer process
- `StreamReader.read(n)` for Content-Length parsing
- Queue for incoming messages (responses + notifications)
- Track `$/progress` notifications for indexing state

Alternative: use `pygls` or `lsprotocol` library (adds dependency — evaluate tradeoff).

## Estimate

2 days (pattern version provides fallback, so no delivery risk).

## Context

- Phase 4.2 pattern version: `core/skills/callgraph_rust.py` (current)
- LSP draft attempt: deleted, issues documented in commit c4b4d3a
- Test workspace: `/tmp/rust_test_workspace` (3 .rs files)
- rust-analyzer installed via `rustup component add rust-analyzer`

## Acceptance test

```bash
# Setup test workspace with trait dispatch
cat > /tmp/rust_test_workspace/src/trait_test.rs <<'EOF'
pub trait Hasher {
    fn hash(&self, data: &str) -> String;
}

pub struct Md5Hasher;
impl Hasher for Md5Hasher {
    fn hash(&self, data: &str) -> String {
        format!("md5:{}", data)
    }
}

pub fn compute_hash(hasher: &dyn Hasher, input: &str) -> String {
    hasher.hash(input)
}
EOF

# Run LSP-based call graph
python3 core/skills/callgraph_rust.py --root /tmp/rust_test_workspace --out /tmp/test.json

# Verify:
# 1. compute_hash → Hasher::hash (trait definition)
# 2. compute_hash → Md5Hasher::hash (impl resolution — stretch goal)
# 3. Indexing completes without timeout
```
