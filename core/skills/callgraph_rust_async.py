#!/usr/bin/env python3
"""callgraph_rust_async.py — Rust call graph via async rust-analyzer LSP (KLC-001).

Implements async LSP client for rust-analyzer with:
- asyncio-based message handling
- Notification/response dispatching
- Workspace indexing wait ($/progress monitoring)
- Call hierarchy extraction

Usage:
    callgraph_rust_async.py --root <path> --out <path>

Output: index/callgraph/rust.json (same schema as pattern version)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.shared.paths import framework_root  # noqa: E402


class AsyncLSPClient:
    """Async LSP client for rust-analyzer."""

    def __init__(self, rust_analyzer_path: str, root: Path):
        self.rust_analyzer_path = rust_analyzer_path
        self.root = root
        self.proc: asyncio.subprocess.Process | None = None
        self.request_id = 0
        self.response_futures: dict[int, asyncio.Future] = {}
        self.indexing_done = asyncio.Event()
        self.read_task: asyncio.Task | None = None

    async def start(self):
        """Start rust-analyzer process and background reader."""
        self.proc = await asyncio.create_subprocess_exec(
            self.rust_analyzer_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.root)
        )
        self.read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        """Background task: read LSP messages, dispatch responses/notifications."""
        try:
            while True:
                # Read Content-Length header
                header = await self.proc.stdout.readline()
                if not header:
                    break

                if not header.startswith(b"Content-Length:"):
                    continue

                length = int(header.decode().split(":")[1].strip())

                # Read blank line
                await self.proc.stdout.readline()

                # Read body
                body = await self.proc.stdout.readexactly(length)
                message = json.loads(body.decode("utf-8"))

                # Handle notifications
                if "method" in message and "id" not in message:
                    await self._handle_notification(message)
                    continue

                # Handle responses
                if "id" in message:
                    msg_id = message["id"]
                    if msg_id in self.response_futures:
                        future = self.response_futures.pop(msg_id)
                        if "error" in message:
                            future.set_exception(RuntimeError(f"LSP error: {message['error']}"))
                        else:
                            future.set_result(message.get("result"))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            sys.stderr.write(f"callgraph_rust: read_loop error: {e}\n")

    async def _handle_notification(self, message: dict):
        """Handle LSP notifications (e.g., $/progress)."""
        method = message.get("method", "")

        if method == "$/progress":
            params = message.get("params", {})
            # Check for workDone completion
            value = params.get("value", {})
            if value.get("kind") == "end":
                self.indexing_done.set()

    async def _send_request(self, method: str, params: dict | None = None) -> dict:
        """Send LSP request and wait for response."""
        self.request_id += 1
        msg_id = self.request_id

        request = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params or {}
        }

        request_json = json.dumps(request)
        content = f"Content-Length: {len(request_json)}\r\n\r\n{request_json}"

        self.proc.stdin.write(content.encode("utf-8"))
        await self.proc.stdin.drain()

        # Create future for response
        future = asyncio.Future()
        self.response_futures[msg_id] = future

        # Wait for response (timeout 30s)
        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
        except asyncio.TimeoutError:
            self.response_futures.pop(msg_id, None)
            raise RuntimeError(f"LSP request timeout: {method}")

    async def _send_notification(self, method: str, params: dict | None = None):
        """Send LSP notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }

        notification_json = json.dumps(notification)
        content = f"Content-Length: {len(notification_json)}\r\n\r\n{notification_json}"

        self.proc.stdin.write(content.encode("utf-8"))
        await self.proc.stdin.drain()

    async def initialize(self):
        """Initialize LSP and wait for workspace indexing."""
        sys.stderr.write("callgraph_rust: initializing rust-analyzer...\n")

        result = await self._send_request("initialize", {
            "processId": os.getpid(),
            "rootUri": f"file://{self.root}",
            "capabilities": {
                "textDocument": {
                    "callHierarchy": {
                        "dynamicRegistration": False
                    }
                },
                "window": {
                    "workDoneProgress": True
                }
            }
        })

        # Send initialized notification
        await self._send_notification("initialized", {})

        sys.stderr.write("callgraph_rust: waiting for indexing...\n")

        # Wait for indexing (timeout 30s)
        try:
            await asyncio.wait_for(self.indexing_done.wait(), timeout=30.0)
            sys.stderr.write("callgraph_rust: indexing complete\n")
        except asyncio.TimeoutError:
            sys.stderr.write("callgraph_rust: indexing timeout — proceeding anyway\n")

        return result

    async def did_open(self, file_uri: str, language_id: str, text: str):
        """Send textDocument/didOpen notification."""
        await self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": file_uri,
                "languageId": language_id,
                "version": 1,
                "text": text
            }
        })

    async def document_symbols(self, file_uri: str) -> list[dict]:
        """Get document symbols."""
        result = await self._send_request("textDocument/documentSymbol", {
            "textDocument": {"uri": file_uri}
        })
        return result if isinstance(result, list) else []

    async def prepare_call_hierarchy(self, file_uri: str, line: int, character: int) -> list[dict]:
        """Prepare call hierarchy for symbol at position."""
        result = await self._send_request("textDocument/prepareCallHierarchy", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character}
        })
        return result if isinstance(result, list) else []

    async def outgoing_calls(self, item: dict) -> list[dict]:
        """Get outgoing calls from call hierarchy item."""
        result = await self._send_request("callHierarchy/outgoingCalls", {
            "item": item
        })
        return result if isinstance(result, list) else []

    async def incoming_calls(self, item: dict) -> list[dict]:
        """Get incoming calls to call hierarchy item."""
        result = await self._send_request("callHierarchy/incomingCalls", {
            "item": item
        })
        return result if isinstance(result, list) else []

    async def shutdown(self):
        """Shutdown rust-analyzer."""
        try:
            await self._send_request("shutdown")
            await self._send_notification("exit")
        except:
            pass
        finally:
            if self.read_task:
                self.read_task.cancel()
                try:
                    await self.read_task
                except asyncio.CancelledError:
                    pass
            if self.proc:
                self.proc.terminate()
                await self.proc.wait()


def find_rust_analyzer() -> str:
    """Find rust-analyzer binary."""
    # Check env var
    if "RUST_ANALYZER" in os.environ:
        path = os.environ["RUST_ANALYZER"]
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
        else:
            sys.stderr.write(f"callgraph_rust: rust-analyzer not found at $RUST_ANALYZER={path}\n")
            sys.stderr.write("  Set $RUST_ANALYZER to valid path or unset to use $PATH\n")
            sys.exit(1)

    # Check PATH
    import subprocess
    result = subprocess.run(
        ["which", "rust-analyzer"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()

    sys.stderr.write("callgraph_rust: rust-analyzer not found\n")
    sys.stderr.write("  Set $RUST_ANALYZER or install rust-analyzer in $PATH\n")
    sys.stderr.write("  Install: rustup component add rust-analyzer\n")
    sys.exit(1)


def collect_rust_files(root: Path) -> list[Path]:
    """Find all .rs files (excluding target/)."""
    files: list[Path] = []
    for path in root.rglob("*.rs"):
        if "/target/" in str(path) or "/.cargo/" in str(path):
            continue
        if path.is_file():
            files.append(path)
    return files


def extract_functions_from_symbols(symbols: list[dict], file_path: str, root: Path) -> list[tuple[str, int, int, str]]:
    """Extract function/method symbols from documentSymbol result.

    Returns: [(qualified_name, line, character, kind)]
    """
    rel_path = str(Path(file_path).relative_to(root))
    functions: list[tuple[str, int, int, str]] = []

    def walk(syms: list[dict], prefix: str = ""):
        for sym in syms:
            kind = sym.get("kind", 0)
            name = sym.get("name", "")

            # DocumentSymbol format: has location.range, no selectionRange
            # Use range.start, which points to the function definition start
            location = sym.get("location", {})
            range_obj = location.get("range", sym.get("range", {}))
            start = range_obj.get("start", {})
            line = start.get("line", 0)
            # Add offset to character to hit the function name, not keywords before it
            # For "pub fn name", the name starts around char 7-10, use middle of name
            char = start.get("character", 0) + len(name) // 2 + 7

            # SymbolKind: Function=12, Method=6
            if kind in (12, 6):
                qualified = f"{prefix}{name}" if prefix else name
                fn_kind = "method" if kind == 6 else "function"
                functions.append((qualified, line, char, fn_kind))

            # Recurse into children (for methods inside impl blocks)
            children = sym.get("children", [])
            if children:
                # If struct/impl/trait, use as prefix
                if kind in (23, 5, 11):  # Struct=23, Impl=5, Trait=11
                    walk(children, f"{prefix}{name}::")
                else:
                    walk(children, prefix)

    walk(symbols)
    return functions


def qualified_name_from_uri(uri: str, name: str, root: Path) -> str:
    """Build qualified name from LSP URI."""
    if uri.startswith("file://"):
        file_path = Path(uri[7:])
        try:
            rel_path = file_path.relative_to(root)
            return f"{rel_path}::{name}"
        except ValueError:
            pass
    return name


async def build_call_graph_async(root: Path, rust_analyzer: str) -> dict[str, dict]:
    """Build call graph using async LSP client."""
    client = AsyncLSPClient(rust_analyzer, root)

    try:
        await client.start()
        await client.initialize()

        files = collect_rust_files(root)
        sys.stderr.write(f"callgraph_rust: found {len(files)} .rs files\n")

        symbols_map: dict[str, dict] = {}

        # Phase 1: Open all files first
        sys.stderr.write("callgraph_rust: opening all files...\n")
        for file_path in files:
            rel_path = file_path.relative_to(root)
            file_uri = f"file://{file_path}"
            try:
                text = file_path.read_text(encoding="utf-8")
                await client.did_open(file_uri, "rust", text)
            except Exception as e:
                sys.stderr.write(f"callgraph_rust: error opening {rel_path}: {e}\n")

        # Wait for rust-analyzer to index all files
        sys.stderr.write("callgraph_rust: waiting for document indexing...\n")
        await asyncio.sleep(2.0)

        # Phase 2: Extract all function symbols
        for file_path in files:
            rel_path = file_path.relative_to(root)
            file_uri = f"file://{file_path}"

            # Get document symbols
            try:
                doc_symbols = await client.document_symbols(file_uri)
            except Exception as e:
                sys.stderr.write(f"callgraph_rust: error getting symbols for {rel_path}: {e}\n")
                continue

            # Extract functions
            functions = extract_functions_from_symbols(doc_symbols, str(file_path), root)

            # For each function, get call hierarchy (with retry on "content modified")
            for qualified, line, char, kind in functions:
                qualified_full = f"{rel_path}::{qualified}"

                # Retry up to 3 times on "content modified" error
                for attempt in range(3):
                    try:
                        # Prepare call hierarchy
                        items = await client.prepare_call_hierarchy(file_uri, line, char)

                        if not items:
                            break

                        item = items[0]

                        # Get outgoing calls (callees)
                        outgoing = await client.outgoing_calls(item)
                        calls = [qualified_name_from_uri(call["to"]["uri"], call["to"]["name"], root)
                                 for call in outgoing]

                        # Get incoming calls (callers)
                        incoming = await client.incoming_calls(item)
                        called_by = [qualified_name_from_uri(call["from"]["uri"], call["from"]["name"], root)
                                     for call in incoming]

                        symbols_map[qualified_full] = {
                            "kind": kind,
                            "file": str(rel_path),
                            "line": line + 1,  # LSP 0-indexed → 1-indexed
                            "calls": sorted(set(calls)),
                            "called_by": sorted(set(called_by)),
                        }
                        break  # Success, exit retry loop

                    except RuntimeError as e:
                        error_str = str(e)
                        # Retry on "content modified" error
                        if "content modified" in error_str and attempt < 2:
                            await asyncio.sleep(0.5)
                            continue
                        else:
                            sys.stderr.write(f"callgraph_rust: error building call hierarchy for {qualified_full}: {e}\n")
                            break

                    except Exception as e:
                        sys.stderr.write(f"callgraph_rust: error building call hierarchy for {qualified_full}: {e}\n")
                        break
        return symbols_map

    finally:
        await client.shutdown()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Root directory (Cargo workspace)")
    ap.add_argument("--out", required=True, help="Output JSON file path")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        sys.stderr.write(f"callgraph_rust: root not found: {root}\n")
        return 1

    # Check for Cargo.toml
    cargo_toml = root / "Cargo.toml"
    if not cargo_toml.exists():
        sys.stderr.write(f"callgraph_rust: warning: no Cargo.toml at {root}\n")

    rust_analyzer = find_rust_analyzer()
    sys.stderr.write(f"callgraph_rust: using {rust_analyzer}\n")

    # Run async
    symbols = asyncio.run(build_call_graph_async(root, rust_analyzer))

    # Write output
    output = {"symbols": symbols}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    print(f"callgraph_rust: indexed {len(symbols)} symbols → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
