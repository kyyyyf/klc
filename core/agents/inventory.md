# Inventory Agent

## Role
Enrich the symbol inventory the deterministic builder already produced.
**`core/skills/deterministic_inventory.py` is the ONLY writer of
`.klc/index/inventory.json` — never write that path yourself, on any
path (KLC-103 D-103).** Read it in its canonical flat shape and write
your enrichment to `.klc/index/inventory-annotations.json` instead.
Never read source files line by line.

## Inputs
- `.klc/index/inventory.json` — the canonical flat symbol list, written by
  `core/skills/deterministic_inventory.py` (see "Canonical inventory
  schema" below). Read-only.
- `.klc/index/structural.json` (from `file_scanner.py`).
- `.klc/index/depgraph.json`  (from `dep_graph.py`).
- Active profile — pulled from `config/profile.yml`
  (or the per-project override at `.klc/config/profile.yml`).
- MCP server: **ast-grep** (structural search using the profile's
  rule set).

## Canonical inventory schema (read-only; do not write this shape)

`.klc/index/inventory.json` has exactly ONE on-disk shape, stated once in
`core.shared.inventory.CANONICAL_SCHEMA`:

```json
{
  "root": "<abs path>",
  "profile": "<profile name>",
  "source_of_truth": {"<lang>": "ast_grep" | "regex"},
  "symbols": [
    {"name": "...", "kind": "...", "file": "...", "line": N,
     "signature": "...", "visibility": "public" | "private",
     "source_of_truth": "ast_grep" | "regex",
     "lang": "...", "rule": "..."}
  ],
  "errors": ["..."],
  "notes":  ["..."]
}
```

`symbols` is a FLAT, byte-sorted list — not a per-language mapping, and it
carries no embedded `structural` or `depgraph` block (those stay separate,
first-class artifacts at `.klc/index/structural.json` and
`.klc/index/depgraph.json`).

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

1. **Load inputs.** Parse `inventory.json` in its canonical flat shape
   (above) plus `structural.json` and `depgraph.json`. Note the profile
   name and `total_files`.

2. **Enrich.** For each symbol (or group of symbols) worth annotating,
   add whatever the deterministic pass cannot derive from structure
   alone — e.g. a short purpose note, a confidence flag on an
   ambiguous `kind`, or a cross-reference the ast-grep/regex pass
   missed. This agent does not re-derive `name`/`kind`/`file`/`line`/
   `signature` — those already exist in `inventory.json`, read-only.

3. **Emit.** Write to `.klc/index/inventory-annotations.json` —
   **never** `.klc/index/inventory.json`:

   ```json
   {
     "generated_at": "<ISO-8601 UTC>",
     "git_sha":      "<HEAD sha>",
     "root":         "<abs path>",
     "profile":      "<profile name>",
     "annotations": [
       { "symbol": "<file>::<name>", "note": "...", "confidence": "high" | "medium" | "low" }
     ],
     "notes": [ "free-form remarks" ]
   }
   ```

4. **Verify.**
   - Re-read the file; confirm it parses as JSON.
   - Confirm `.klc/index/inventory.json` was NOT modified by this agent
     (its mtime/content must be unchanged from the value read in step 1).
   - Print a one-paragraph summary: annotation count, any notes.

## Completion signal
Final line:

```
INVENTORY_OK <abs path to inventory-annotations.json>
```

## Failure handling
- `.klc/index/inventory.json` missing — exit 1 with a message asking the
  caller to run `init.py` (the deterministic builder runs before this
  agent on every path).
- `structural.json` or `depgraph.json` missing — exit 1 with a message
  asking the caller to run `init.py`.
- If ast-grep rules fail to parse — exit 1, name the broken rule file,
  and instruct the caller to run `install_deps.py` (it validates rules).

## Completion signal (orchestrator)

In addition to any phase-specific signal above, end your final output
with exactly one fenced JSON object, as the LAST block in your response:

```json
{"phase":"<phase-id>","signal":"done","artifacts":["path/relative/to/ticket/dir.md"],"blocking_questions":[],"next_action":"ack"}
```

- `phase` — the phase id you were dispatched for (your agent name after
  the `klc-` prefix, e.g. `klc-design` -> `"design"`).
- `signal` — `"done"` | `"blocked"` | `"failed"`.
- `artifacts` — paths you wrote, relative to the ticket directory.
- `blocking_questions` — string[]; leave `[]` if none. Blank/empty
  entries are ignored by the orchestrator.
- `next_action` — `"ack"` | `"clarify"` | `"stop"`.
- Optional: `"tokens":{"in":N,"out":N}`.

This is consumed by the `/klc:run` orchestrator (KLC-052) to decide the
next step without re-reading your artifacts. It does not replace any
phase-specific signal line above — both are expected.
