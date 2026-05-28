---
ticket: KLC-001
authority: hybrid
last_generated: 2026-05-28T09:20:00Z
---

# Test plan — KLC-001

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_callgraph_rust_lsp.py::test_basic_edges | Test workspace with register_user → auth::hash_password, db::insert_user |
| AC-2 | acceptance | tests/test_callgraph_rust_lsp.py::test_trait_dispatch | Trait + impl resolution (stretch goal — can defer if LSP doesn't support) |
| AC-3 | acceptance | tests/test_callgraph_rust_lsp.py::test_performance | 100k-LOC workspace under 30s |
| AC-4 | acceptance | tests/test_callgraph_rust_lsp.py::test_fallback_missing_analyzer | rust-analyzer not found → clear error |

## Edge cases

- **Empty workspace**: Cargo.toml present but no .rs files → empty graph, no error
- **Indexing timeout**: rust-analyzer doesn't complete indexing in 30s → log warning, proceed with partial results
- **Invalid Rust code**: syntax errors in .rs files → LSP should skip those files, log warning
- **Mixed language project**: Rust + Python → only Rust files indexed, others ignored
- **Nested modules**: src/module/submodule.rs → qualified names correct (`module::submodule::function`)
- **Trait objects**: `dyn Trait` calls → resolve to trait definition only (impl dispatch runtime-only)

## Regression scenarios

- **Pattern version still works**: After LSP implementation, pattern-based version backed up as `callgraph_rust_pattern.py.bak` — verify it still runs if needed
- **Output schema unchanged**: LSP version produces same JSON structure as pattern version (`{symbols: {<name>: {kind, file, line, calls, called_by}}}`)
- **Call graph from previous sessions**: Existing `index/callgraph/rust.json` from pattern version → regenerate with LSP version, verify no schema breakage for downstream consumers (context-loader, review.py)

## Manual checklist

- [ ] Run on klc itself (if klc has Rust code, otherwise use external Rust project)
- [ ] Compare token counts before/after: LSP vs pattern version for same project
- [ ] Verify trait dispatch: manually inspect output for trait method → impl resolution
- [ ] Check indexing wait: monitor $/progress notifications in logs

## Detailed coverage

<!-- TBD — populated in phase 4 after Design -->

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
