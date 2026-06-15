---
name: klc-inventory
description: klc inventory phase agent
model: sonnet
---
# Inventory Agent

## Role
Produce `.klc/index/inventory.json` — a complete, language-aware
snapshot of the project. Never read source files line by line.

## Inputs
- `.klc/index/structural.json` (from `file_scanner.py`).
- `.klc/index/depgraph.json`  (from `dep_graph.py`).
- Active profile — pulled from `config/profile.yml`
  (or the per-project override at `.klc/config/profile.yml`).
- MCP server: **ast-grep** (structural search using the profile's
  rule set).

## Symbol source of truth
**Bootstrap is deterministic-only: do not call LSP from this agent.**
A full LSP walk on a large project is expensive; symbol names (capped
at 15) are all the module CLAUDE.md templates consume anyway.

Order of preference inside this agent:

1. Structured indices already on disk (`.klc/index/structural.json`,
   `.klc/index/depgraph.json`).
2. Profile ast-grep rules — structural patterns (UE macros, decorators,
   language-specific public-API shape).
3. Regex fallback — allowed, but record it in `source_of_truth` so
   downstream agents know the data is less precise.

LSP enters the picture during ticket work (design/impl/build) when an
agent needs to verify a specific symbol signature or find references.

## Steps

1. **Load inputs.** Parse the two index JSONs. Note the profile name
   and `total_files`.

2. **Enumerate symbols per language.** For each language in
   `structural.languages`:

   - Iterate over `structural.source_roots` as the search scope.
   - Collect **public** symbols:
     - Python — not `_`-prefixed, or listed in `__all__`.
     - TS/JS — `export` declarations.
     - C++ — class/struct/function declarations in headers.
     - Rust — items with `pub` visibility.
   - Record `{name, kind, file, line, signature}` per symbol.
   - If a language exceeds 20 000 symbols, switch it to summary mode
     (keep `{by_dir: {<rel-dir>: N}}` instead of `items[]`).

3. **Emit.** Write to `.klc/index/inventory.json`:

   ```json
   {
     "generated_at":    "<ISO-8601 UTC>",
     "git_sha":         "<HEAD sha>",
     "root":            "<abs path>",
     "profile":         "<profile name>",
     "structural":      { ... },
     "depgraph":        { ... },
     "source_of_truth": { "<lang>": "ast_grep" | "regex_fallback" },
     "symbols": {
       "<language>": {
         "mode":   "detailed" | "summary",
         "count":  N,
         "items":  [ { "name": "...", "kind": "...", "file": "...", "line": N, "signature": "..." } ],
         "by_dir": { "<rel-dir>": N }
       }
     },
     "notes": [ "free-form remarks" ]
   }
   ```

   `source_of_truth[lang]` is mandatory:
   - `ast_grep` — ast-grep rule from the profile's rule set.
   - `regex_fallback` — ast-grep rule unavailable or failed.

4. **Verify.**
   - Re-read the file; confirm it parses as JSON.
   - For detailed mode, `count == len(items)`.
   - Print a one-paragraph summary: counts per language, top 5
     directories by file count, any notes.

## Completion signal
Final line:

```
INVENTORY_OK <abs path to inventory.json>
```

## Failure handling
- `structural.json` or `depgraph.json` missing — exit 1 with a message
  asking the caller to run `init.py`.
- If ast-grep rules fail to parse — exit 1, name the broken rule file,
  and instruct the caller to run `install_deps.py` (it validates rules).
