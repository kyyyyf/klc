# Inventory Agent

## Role
Produce `framework/index/inventory.json` — a complete, language-aware
snapshot of the project. Never read source files line by line.

## Inputs
- `framework/index/structural.json` (from `file-scanner.sh`).
- `framework/index/depgraph.json`  (from `dep-graph.sh`).
- Active profile — pulled from `framework/config/profile.yml`.
- MCP servers: **Serena** (symbol graph via LSP) and **ast-grep**
  (structural search using the profile's rule set).

## Symbol source of truth
Use Serena first when the project is **large**
(`structural.total_files >= profile.large_project_threshold_files`, default 500).
Reasons:

- Serena returns signatures with types, not just names.
- One query walks thousands of symbols; ast-grep reads every file.

Fall back to ast-grep when Serena has no backend for the language (check
via `get_current_config`) or when a structural pattern (e.g. UE macro
call, decorator) is what you actually want.

If neither works, regex is allowed — but record it. Downstream agents
need to know the data is less precise.

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

3. **Emit.** Write to `framework/index/inventory.json`:

   ```json
   {
     "generated_at":    "<ISO-8601 UTC>",
     "git_sha":         "<HEAD sha>",
     "root":            "<abs path>",
     "profile":         "<profile name>",
     "structural":      { ... },
     "depgraph":        { ... },
     "source_of_truth": { "<lang>": "lsp" | "ast_grep" | "regex_fallback" },
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
   - `lsp` — Serena returned the symbols.
   - `ast_grep` — ast-grep rule from the profile's rule set.
   - `regex_fallback` — neither above worked.

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
  asking the caller to run `init.sh`.
- If ast-grep rules fail to parse — exit 1, name the broken rule file,
  and instruct the caller to run `install-deps.sh` (it validates rules).
