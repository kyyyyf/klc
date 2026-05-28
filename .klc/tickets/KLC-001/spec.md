---
ticket: KLC-001
kind: feature
authority: human
last_generated: 2026-05-28T08:45:00Z
---

# KLC-001 — Rust LSP call graph integration via rust-analyzer

## Goals

Upgrade `core/skills/callgraph_rust.py` from pattern-based parsing to rust-analyzer LSP integration for compiler-accurate call graphs.

## Problem / Context

Phase 4.2 (commit c4b4d3a) implemented pattern-based Rust call graph extraction using regex. Limitations:
- ~70% accuracy: misses macro-generated code, trait dispatch to impls, complex generics
- Synchronous LSP client attempt failed: rust-analyzer sends interleaved notifications/responses, workspace indexing not awaited

> [!FACT F-001] src=core/skills/callgraph_rust.py:1-30 verified=2026-05-28
> Current implementation uses regex patterns for `fn` definitions and `module::function(` calls. Does not use LSP.

rust-analyzer LSP provides:
- `textDocument/prepareCallHierarchy` — get call hierarchy item for a symbol
- `callHierarchy/outgoingCalls` — callees
- `callHierarchy/incomingCalls` — callers
- Trait method resolution to visible impls

## Acceptance Criteria

1. **AC-1**: Given test workspace with 3 .rs files and 6 functions, LSP version produces same call edges as pattern version (register_user → auth::hash_password, db::insert_user)
2. **AC-2**: Given trait definition + impl, resolves trait method calls to both trait definition AND impl (stretch goal: can be deferred to AC if LSP doesn't provide impl resolution)
3. **AC-3**: Runtime under 30s on 100k-LOC Rust workspace (rust-analyzer indexing is main bottleneck, not our code)
4. **AC-4**: Falls back gracefully with clear error if rust-analyzer not found in $PATH or $RUST_ANALYZER env

## Non-goals

- Cross-crate call graph (workspace-only, external dependencies ignored)
- Macro expansion beyond what rust-analyzer provides
- Support for Rust editions < 2018

## Constraints

> [!CONSTRAINT C-001] source=klc design principle
> No external Python dependencies beyond stdlib. Cannot use `pygls` or `lsprotocol` libraries.

> [!CONSTRAINT C-002] source=Phase 4 acceptance criteria (PHASE4_PLAN.md)
> Must produce same JSON schema as Python call graph: `{symbols: {<qualified_name>: {kind, file, line, calls: [], called_by: []}}}`

> [!CONSTRAINT C-003] source=rust-analyzer behavior
> LSP server requires workspace indexing (5-30s for large projects) before returning call hierarchy results. Must wait for `$/progress` notifications or timeout.

## Affected modules

- `core/skills/callgraph_rust.py`: full rewrite from pattern-based to LSP-based

## Technical approach

### Async LSP client (stdlib asyncio)

```python
import asyncio
import json
from pathlib import Path

class AsyncLSPClient:
    def __init__(self, rust_analyzer_path: str, root: Path):
        self.proc = None  # asyncio.subprocess.Process
        self.request_id = 0
        self.message_queue = asyncio.Queue()
        self.indexing_done = asyncio.Event()
    
    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            rust_analyzer_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(root)
        )
        asyncio.create_task(self._read_loop())
    
    async def _read_loop(self):
        """Background task: read LSP messages, dispatch to queue or handle notifications."""
        while True:
            # Read Content-Length header
            header_line = await self.proc.stdout.readline()
            if not header_line:
                break
            if b"Content-Length:" in header_line:
                length = int(header_line.decode().split(":")[1].strip())
                await self.proc.stdout.readline()  # empty line
                body = await self.proc.stdout.readexactly(length)
                message = json.loads(body)
                
                # Handle $/progress notifications
                if message.get("method") == "$/progress":
                    if "workDone" in str(message.get("params", {})):
                        self.indexing_done.set()
                
                # Queue response messages
                if "id" in message:
                    await self.message_queue.put(message)
    
    async def initialize(self):
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "processId": os.getpid(),
                "rootUri": f"file://{self.root}",
                "capabilities": {"textDocument": {"callHierarchy": {}}}
            }
        }
        await self._send(request)
        response = await self._wait_response(request["id"])
        
        # Send initialized notification
        await self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        
        # Wait for indexing (timeout 30s)
        try:
            await asyncio.wait_for(self.indexing_done.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            sys.stderr.write("rust-analyzer indexing timeout — proceeding anyway\n")
```

### Steps

1. Replace synchronous subprocess with `asyncio.create_subprocess_exec`
2. Background `_read_loop` task for incoming messages (responses + notifications)
3. Track `$/progress` notifications, set event when `workDone` appears
4. Await indexing event (timeout 30s) after `initialize`
5. Iterate files: `didOpen` → `textDocument/documentSymbol` → extract functions → `prepareCallHierarchy` → `outgoingCalls` + `incomingCalls`
6. Same output format as current version

## Open questions

> [!QUESTION Q-001] blocks=none
> Does rust-analyzer's `callHierarchy/outgoingCalls` resolve trait methods to impls, or only to trait definitions? If only trait definitions, AC-2 is a stretch goal.
> **Resolution approach**: test with trait_test.rs acceptance test, inspect results.

> [!QUESTION Q-002] blocks=none
> Can we detect indexing completion reliably via `$/progress`, or should we use a fixed sleep after initialize?
> **Resolution approach**: implement both (event-based + fallback timeout), log which triggered.

## Estimate

- complexity: 2 (async I/O + LSP protocol, but well-documented)
- uncertainty: 1 (LSP protocol is standard, rust-analyzer behavior documented)
- risk: 0 (pattern version provides fallback if LSP fails)
- manual: 1 (need to verify trait dispatch manually, auto-tests cover basic edges)
- total: 4
- track: S

## Related work

- Phase 4.1 (commit ac868c8): Python call graph (pattern-based, works)
- Phase 4.2 (commit c4b4d3a): Rust call graph (pattern-based MVP, documented limitations)
- LSP draft attempt: deleted in c4b4d3a (sync client, no indexing wait)

## Test plan

1. Run current pattern version on test workspace, record edges → baseline
2. Implement async LSP client, test initialize + indexing wait
3. Test `prepareCallHierarchy` on known function, verify non-empty result
4. Full integration: compare LSP edges vs pattern baseline
5. Add trait_test.rs (trait + impl), verify resolution (Q-001)
6. Performance test on klc itself (~60 .rs files equivalent for C++ if present, or use external Rust project)
