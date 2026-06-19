#!/usr/bin/env python3
"""callgraph_cpp.py — C++ call graph via clangd LSP (KLC-004).

Implements an async LSP client for clangd mirroring callgraph_rust_async.py:
- asyncio-based message handling with response/notification dispatch
- Workspace indexing wait ($/progress monitoring)
- documentSymbol + callHierarchy extraction per translation unit
- Compact file:line references via textDocument/references (AC-4)

Usage:
    callgraph_cpp.py --backend clangd --compdb <path/to/compile_commands.json> --out <path>

Output: index/callgraph/cpp.json — same schema as python.json / rust.json:
    {symbols: {id: {kind, file, line, calls, called_by}}}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))


class AsyncLSPClient:
    """Async LSP client for clangd."""

    def __init__(self, clangd_path: str, root: Path, compdb_dir: Path):
        self.clangd_path = clangd_path
        self.root = root
        self.compdb_dir = compdb_dir
        self.proc: asyncio.subprocess.Process | None = None
        self.request_id = 0
        self.response_futures: dict[int, asyncio.Future] = {}
        self.indexing_done = asyncio.Event()
        self.read_task: asyncio.Task | None = None

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            self.clangd_path,
            f"--compile-commands-dir={self.compdb_dir}",
            "--log=error",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.root),
        )
        self.read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        try:
            while True:
                header = await self.proc.stdout.readline()
                if not header:
                    break
                if not header.startswith(b"Content-Length:"):
                    continue
                length = int(header.decode().split(":")[1].strip())
                await self.proc.stdout.readline()
                body = await self.proc.stdout.readexactly(length)
                message = json.loads(body.decode("utf-8"))

                if "method" in message and "id" not in message:
                    await self._handle_notification(message)
                    continue

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
            sys.stderr.write(f"callgraph_cpp: read_loop error: {e}\n")

    async def _handle_notification(self, message: dict):
        method = message.get("method", "")
        if method == "$/progress":
            value = message.get("params", {}).get("value", {})
            if value.get("kind") == "end":
                self.indexing_done.set()
        # window/workDoneProgress/create is acknowledged implicitly (no response needed)

    async def _send_request(self, method: str, params: dict | None = None) -> dict:
        self.request_id += 1
        msg_id = self.request_id
        request = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}
        request_json = json.dumps(request)
        content = f"Content-Length: {len(request_json)}\r\n\r\n{request_json}"
        self.proc.stdin.write(content.encode("utf-8"))
        await self.proc.stdin.drain()

        future = asyncio.Future()
        self.response_futures[msg_id] = future
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self.response_futures.pop(msg_id, None)
            raise RuntimeError(f"LSP request timeout: {method}")

    async def _send_notification(self, method: str, params: dict | None = None):
        notification = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        notification_json = json.dumps(notification)
        content = f"Content-Length: {len(notification_json)}\r\n\r\n{notification_json}"
        self.proc.stdin.write(content.encode("utf-8"))
        await self.proc.stdin.drain()

    async def initialize(self):
        sys.stderr.write("callgraph_cpp: initializing clangd...\n")
        await self._send_request("initialize", {
            "processId": os.getpid(),
            "rootUri": f"file://{self.root}",
            "capabilities": {
                "textDocument": {
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    "callHierarchy": {"dynamicRegistration": False},
                    "references": {},
                },
                "window": {"workDoneProgress": True},
            },
        })
        await self._send_notification("initialized", {})

    async def did_open(self, file_uri: str, text: str):
        await self._send_notification("textDocument/didOpen", {
            "textDocument": {"uri": file_uri, "languageId": "cpp", "version": 1, "text": text}
        })

    async def document_symbols(self, file_uri: str) -> list[dict]:
        result = await self._send_request("textDocument/documentSymbol", {
            "textDocument": {"uri": file_uri}
        })
        return result if isinstance(result, list) else []

    async def prepare_call_hierarchy(self, file_uri: str, line: int, character: int) -> list[dict]:
        result = await self._send_request("textDocument/prepareCallHierarchy", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
        })
        return result if isinstance(result, list) else []

    async def incoming_calls(self, item: dict) -> list[dict]:
        result = await self._send_request("callHierarchy/incomingCalls", {"item": item})
        return result if isinstance(result, list) else []

    async def find_references(self, file_uri: str, line: int, character: int) -> list[dict]:
        """Return all reference locations for a symbol (AC-4)."""
        result = await self._send_request("textDocument/references", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": False},
        })
        return result if isinstance(result, list) else []

    async def workspace_symbol(self, query: str) -> list[dict]:
        """Find symbols in the workspace matching query (AC-4/D-002)."""
        result = await self._send_request("workspace/symbol", {"query": query})
        return result if isinstance(result, list) else []

    async def go_to_implementation(self, file_uri: str, line: int, character: int) -> list[dict]:
        """Best-effort virtual-override resolution (AC-2)."""
        try:
            result = await self._send_request("textDocument/implementation", {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
            })
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return [result]
        except RuntimeError:
            pass
        return []

    async def shutdown(self):
        try:
            await self._send_request("shutdown")
            await self._send_notification("exit")
        except Exception:
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


def find_clangd() -> str:
    """Locate clangd binary: $CLANGD env var, then PATH."""
    if "CLANGD" in os.environ:
        path = os.environ["CLANGD"]
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        sys.stderr.write(f"callgraph_cpp: clangd not found at $CLANGD={path}\n")
        sys.stderr.write("  Set $CLANGD to a valid path or unset to use PATH\n")
        sys.exit(1)

    path = shutil.which("clangd")
    if path:
        return path

    sys.stderr.write("callgraph_cpp: clangd not found on PATH\n")
    sys.stderr.write("  Install clangd: https://clangd.llvm.org/installation\n")
    sys.stderr.write("  Or set $CLANGD to the binary path\n")
    sys.exit(1)


def load_compdb(compdb_path: Path) -> list[dict]:
    """Read compile_commands.json and return the entries."""
    return json.loads(compdb_path.read_text(encoding="utf-8"))


_EXCLUDE_DIRS = frozenset({
    "build", "cmake-build", "_build", ".build", "out", "install",
    "_deps", "CMakeFiles", ".klc", ".git", "node_modules", "__pycache__",
})


def collect_header_files(root: Path) -> list[Path]:
    """Find header files that may contain header-only / inline functions.

    Excludes common build output directories and the .klc state directory.
    """
    headers: list[Path] = []
    seen: set[str] = set()

    for ext in ("*.h", "*.hpp", "*.hh", "*.hxx"):
        for p in root.rglob(ext):
            if not p.is_file():
                continue
            try:
                parts = p.relative_to(root).parts[:-1]
            except ValueError:
                continue
            if any(d in _EXCLUDE_DIRS for d in parts):
                continue
            key = str(p.resolve())
            if key not in seen:
                seen.add(key)
                headers.append(p.resolve())

    headers.sort()
    return headers


def collect_tu_files(compdb: list[dict]) -> list[Path]:
    """Return absolute paths of translation units from compile_commands.json."""
    tu_exts = {".cpp", ".cc", ".cxx", ".c", ".C"}
    files: list[Path] = []
    seen: set[str] = set()
    for entry in compdb:
        p = Path(entry["file"])
        if not p.is_absolute():
            p = Path(entry.get("directory", "")) / p
        p = p.resolve()
        key = str(p)
        if key not in seen and p.suffix.lower() in tu_exts:
            seen.add(key)
            files.append(p)
    return files


def _sel_range_pos(sym: dict) -> tuple[int, int]:
    """Return (line, char) from selectionRange (or range) for call hierarchy."""
    sel = sym.get("selectionRange") or sym.get("range") or {}
    start = sel.get("start", {})
    name = sym.get("name", "")
    line = start.get("line", 0)
    char = start.get("character", 0) + len(name) // 2
    return line, char


def extract_functions(symbols: list[dict], file_uri: str, root: Path) -> list[tuple[str, int, int, str]]:
    """Recursively extract function/method symbols from documentSymbol result.

    Returns: [(qualified_name, line, char, kind_str)]
    """
    file_path = Path(file_uri[7:]) if file_uri.startswith("file://") else Path(file_uri)
    try:
        rel = str(file_path.relative_to(root))
    except ValueError:
        rel = str(file_path)

    # SymbolKind values from LSP spec
    _FUNCTION = 12
    _METHOD = 6
    _CONSTRUCTOR = 9

    results: list[tuple[str, int, int, str]] = []

    def walk(syms: list[dict], prefix: str):
        for sym in syms:
            kind = sym.get("kind", 0)
            name = sym.get("name", "")
            line, char = _sel_range_pos(sym)

            if kind in (_FUNCTION, _METHOD, _CONSTRUCTOR):
                qname = f"{prefix}{name}" if prefix else name
                kind_str = "method" if kind in (_METHOD, _CONSTRUCTOR) else "function"
                results.append((qname, line, char, kind_str))

            children = sym.get("children", [])
            if children:
                # Class/Struct/Namespace: descend with qualified prefix
                if kind in (5, 23, 3, 10):  # Class, Struct, Namespace, Enum
                    walk(children, f"{prefix}{name}::")
                else:
                    walk(children, prefix)

    walk(symbols, "")
    return [(f"{rel}::{qname}", line, char, kind_str) for qname, line, char, kind_str in results]


def _uri_to_sym_id(uri: str, name: str, root: Path) -> str:
    """Build symbol-map key from call hierarchy item uri + name."""
    if uri.startswith("file://"):
        p = Path(uri[7:])
        try:
            rel = str(p.relative_to(root))
            return f"{rel}::{name}"
        except ValueError:
            pass
    return name


async def build_call_graph_async(root: Path, compdb_path: Path, clangd: str) -> dict[str, dict]:
    """Build call graph using clangd LSP.

    clangd 18 supports callHierarchy/incomingCalls but NOT outgoingCalls.
    Strategy: for every symbol collect incomingCalls (callers) → called_by;
    then derive calls as the inverse within the tracked symbol set.
    """
    client = AsyncLSPClient(clangd, root, compdb_path.parent)

    try:
        await client.start()
        await client.initialize()

        compdb = load_compdb(compdb_path)
        tu_files = collect_tu_files(compdb)
        header_files = collect_header_files(root)
        sys.stderr.write(
            f"callgraph_cpp: found {len(tu_files)} TU(s) in compile_commands.json, "
            f"{len(header_files)} header(s)\n"
        )

        # Phase 1: open TUs first (establish compilation context), then headers
        sys.stderr.write("callgraph_cpp: opening TU files...\n")
        for file_path in tu_files:
            file_uri = f"file://{file_path}"
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                await client.did_open(file_uri, text)
            except Exception as e:
                sys.stderr.write(f"callgraph_cpp: error opening {file_path.name}: {e}\n")

        sys.stderr.write("callgraph_cpp: opening header files...\n")
        for file_path in header_files:
            file_uri = f"file://{file_path}"
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                await client.did_open(file_uri, text)
            except Exception as e:
                sys.stderr.write(f"callgraph_cpp: error opening {file_path.name}: {e}\n")

        # Wait for clangd to finish indexing now that files are open
        sys.stderr.write("callgraph_cpp: waiting for indexing...\n")
        try:
            await asyncio.wait_for(client.indexing_done.wait(), timeout=15.0)
            sys.stderr.write("callgraph_cpp: indexing complete\n")
        except asyncio.TimeoutError:
            sys.stderr.write("callgraph_cpp: indexing timeout — proceeding\n")
        await asyncio.sleep(2.0)

        # Phase 2: collect all symbols + their call-hierarchy items
        # TUs iterated before headers so dedup keeps TU-attributed entries for
        # functions declared in a header but defined in a .cpp (AC-3).
        sym_items: list[tuple[str, dict, dict]] = []  # (canonical_id, entry, ch_item)

        for file_path in tu_files + header_files:
            file_uri = f"file://{file_path}"
            try:
                doc_syms = await client.document_symbols(file_uri)
            except Exception as e:
                sys.stderr.write(f"callgraph_cpp: documentSymbol failed for {file_path.name}: {e}\n")
                continue

            functions = extract_functions(doc_syms, file_uri, root)
            sys.stderr.write(f"callgraph_cpp: {file_path.name}: {len(functions)} function(s)\n")

            for sym_id, line, char, kind_str in functions:
                try:
                    items = await client.prepare_call_hierarchy(file_uri, line, char)
                    if not items:
                        continue

                    item = items[0]
                    item_uri = item.get("uri", file_uri)
                    item_name = item.get("name", sym_id.rsplit("::", 1)[-1])
                    canonical_id = _uri_to_sym_id(item_uri, item_name, root)

                    try:
                        item_file = str(Path(item_uri[7:]).relative_to(root))
                    except (ValueError, Exception):
                        item_file = item_uri

                    entry: dict = {
                        "kind": kind_str,
                        "file": item_file,
                        "line": item.get("range", {}).get("start", {}).get("line", line) + 1,
                        "calls": [],
                        "called_by": [],
                    }
                    sym_items.append((canonical_id, entry, item))

                except RuntimeError as e:
                    if "content modified" in str(e):
                        await asyncio.sleep(0.5)
                    else:
                        sys.stderr.write(f"callgraph_cpp: call hierarchy failed for {sym_id}: {e}\n")
                except Exception as e:
                    sys.stderr.write(f"callgraph_cpp: error processing {sym_id}: {e}\n")

        # Build symbol map (dedup by canonical_id)
        symbols_map: dict[str, dict] = {}
        item_by_id: dict[str, dict] = {}
        for canonical_id, entry, item in sym_items:
            if canonical_id not in symbols_map:
                symbols_map[canonical_id] = entry
                item_by_id[canonical_id] = item

        # Phase 3: incomingCalls for each symbol → populate called_by + inverse calls
        for canonical_id, item in item_by_id.items():
            try:
                incoming = await client.incoming_calls(item)
                callers = sorted(set(
                    _uri_to_sym_id(c["from"]["uri"], c["from"]["name"], root)
                    for c in incoming
                ))
                symbols_map[canonical_id]["called_by"] = callers
                # Derive calls: each caller's calls list gains this symbol
                for caller_id in callers:
                    if caller_id in symbols_map:
                        symbols_map[caller_id]["calls"].append(canonical_id)
            except Exception as e:
                sys.stderr.write(f"callgraph_cpp: incomingCalls failed for {canonical_id}: {e}\n")

        # Phase 4: sort all calls lists + collect find_references (AC-4)
        for canonical_id, entry in symbols_map.items():
            entry["calls"] = sorted(set(entry["calls"]))
            item = item_by_id.get(canonical_id)
            if item:
                ref_pos = item.get("selectionRange", {}).get("start", {})
                item_uri = item.get("uri", "")
                try:
                    ref_locs = await client.find_references(
                        item_uri,
                        ref_pos.get("line", 0),
                        ref_pos.get("character", 0),
                    )
                    refs: list[str] = []
                    for loc in ref_locs:
                        loc_uri = loc.get("uri", "")
                        loc_line = loc.get("range", {}).get("start", {}).get("line", 0) + 1
                        try:
                            loc_file = str(Path(loc_uri[7:]).relative_to(root))
                        except (ValueError, Exception):
                            loc_file = loc_uri
                        refs.append(f"{loc_file}:{loc_line}")
                    if refs:
                        entry["references"] = sorted(set(refs))
                except Exception:
                    pass

        # Phase 4b: best-effort virtual-override resolution (AC-2)
        for canonical_id, entry in symbols_map.items():
            if entry.get("kind") != "method":
                continue
            item = item_by_id.get(canonical_id)
            if not item:
                continue
            try:
                item_uri = item.get("uri", "")
                item_sel = item.get("selectionRange", {}).get("start", {})
                impl_locs = await client.go_to_implementation(
                    item_uri, item_sel.get("line", 0), item_sel.get("character", 0)
                )
                impls: list[str] = []
                for loc in impl_locs:
                    loc_uri = loc.get("uri") or loc.get("targetUri", "")
                    range_obj = (
                        loc.get("range")
                        or loc.get("targetSelectionRange")
                        or loc.get("targetRange")
                        or {}
                    )
                    loc_line = range_obj.get("start", {}).get("line", 0) + 1
                    try:
                        loc_file = str(Path(loc_uri[7:]).relative_to(root))
                    except (ValueError, Exception):
                        loc_file = loc_uri
                    loc_str = f"{loc_file}:{loc_line}"
                    # Filter self-reference so only distinct overrides are recorded
                    if loc_str != f"{entry['file']}:{entry['line']}":
                        impls.append(loc_str)
                if impls:
                    entry["implementations"] = sorted(set(impls))
            except Exception:
                pass

        return symbols_map

    finally:
        await client.shutdown()


async def query_references_async(root: Path, compdb_path: Path, clangd: str, symbol_name: str) -> list[str]:
    """Find all references to symbol_name, returning sorted file:line strings (AC-4/D-002)."""
    client = AsyncLSPClient(clangd, root, compdb_path.parent)
    try:
        await client.start()
        await client.initialize()

        compdb = load_compdb(compdb_path)
        tu_files = collect_tu_files(compdb)
        header_files = collect_header_files(root)
        for file_path in tu_files + header_files:
            file_uri = f"file://{file_path}"
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                await client.did_open(file_uri, text)
            except Exception as e:
                sys.stderr.write(f"callgraph_cpp: error opening {file_path.name}: {e}\n")
        try:
            await asyncio.wait_for(client.indexing_done.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            pass
        await asyncio.sleep(2.0)

        sym_results = await client.workspace_symbol(symbol_name)
        refs: set[str] = set()
        for sym in sym_results:
            loc = sym.get("location", {})
            sym_uri = loc.get("uri", "")
            sym_pos = loc.get("range", {}).get("start", {})
            if not sym_uri.startswith("file://"):
                continue
            try:
                Path(sym_uri[7:]).relative_to(root)
            except ValueError:
                continue  # outside project root
            ref_locs = await client.find_references(
                sym_uri, sym_pos.get("line", 0), sym_pos.get("character", 0),
            )
            for ref_loc in ref_locs:
                ref_uri = ref_loc.get("uri", "")
                ref_line = ref_loc.get("range", {}).get("start", {}).get("line", 0) + 1
                try:
                    ref_file = str(Path(ref_uri[7:]).relative_to(root))
                except (ValueError, Exception):
                    ref_file = ref_uri
                refs.add(f"{ref_file}:{ref_line}")
        return sorted(refs)
    finally:
        await client.shutdown()


async def query_workspace_symbol_async(root: Path, compdb_path: Path, clangd: str, symbol_name: str) -> list[str]:
    """Find workspace symbols by name, returning sorted file:line strings (AC-4/D-002)."""
    client = AsyncLSPClient(clangd, root, compdb_path.parent)
    try:
        await client.start()
        await client.initialize()

        compdb = load_compdb(compdb_path)
        tu_files = collect_tu_files(compdb)
        header_files = collect_header_files(root)
        for file_path in tu_files + header_files:
            file_uri = f"file://{file_path}"
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                await client.did_open(file_uri, text)
            except Exception as e:
                sys.stderr.write(f"callgraph_cpp: error opening {file_path.name}: {e}\n")
        try:
            await asyncio.wait_for(client.indexing_done.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            pass
        await asyncio.sleep(2.0)

        sym_results = await client.workspace_symbol(symbol_name)
        locs: set[str] = set()
        for sym in sym_results:
            loc = sym.get("location", {})
            uri = loc.get("uri", "")
            line = loc.get("range", {}).get("start", {}).get("line", 0) + 1
            if not uri.startswith("file://"):
                continue
            try:
                file = str(Path(uri[7:]).relative_to(root))
            except ValueError:
                continue  # outside project root
            locs.add(f"{file}:{line}")
        return sorted(locs)
    finally:
        await client.shutdown()


def main() -> int:
    ap = argparse.ArgumentParser(description="C++ call graph via clangd LSP")
    ap.add_argument("--backend", default="clangd", choices=["clangd"],
                    help="LSP backend (only clangd supported)")
    ap.add_argument("--compdb", required=True,
                    help="Path to compile_commands.json (or directory containing it)")
    ap.add_argument("--out", help="Output JSON file path (required without --query)")
    ap.add_argument("--query", choices=["references", "workspace-symbol"],
                    help="Query mode: find references or workspace symbols (prints JSON to stdout)")
    ap.add_argument("--symbol", help="Symbol name for --query mode")
    args = ap.parse_args()

    compdb_path = Path(args.compdb)
    if compdb_path.is_dir():
        compdb_path = compdb_path / "compile_commands.json"

    if not compdb_path.exists():
        sys.stderr.write(f"callgraph_cpp: compile_commands.json not found: {compdb_path}\n")
        sys.stderr.write("  Generate it with: cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON <src>\n")
        return 1

    clangd = find_clangd()
    sys.stderr.write(f"callgraph_cpp: using {clangd}\n")

    root = compdb_path.parent.resolve()

    if args.query:
        if not args.symbol:
            sys.stderr.write("callgraph_cpp: --symbol is required with --query\n")
            return 1
        if args.query == "references":
            results = asyncio.run(
                query_references_async(root, compdb_path.resolve(), clangd, args.symbol)
            )
        else:
            results = asyncio.run(
                query_workspace_symbol_async(root, compdb_path.resolve(), clangd, args.symbol)
            )
        print(json.dumps(results))
        return 0

    if not args.out:
        sys.stderr.write("callgraph_cpp: --out is required without --query\n")
        return 1

    # Workspace root = directory containing compile_commands.json
    symbols = asyncio.run(build_call_graph_async(root, compdb_path.resolve(), clangd))

    output = {"symbols": symbols}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    print(f"callgraph_cpp: indexed {len(symbols)} symbols → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
