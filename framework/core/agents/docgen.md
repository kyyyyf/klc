# Docgen Agent

## Role
Generate the `CLAUDE.md` documentation tree:
- One root `CLAUDE.md` at the project root.
- One `CLAUDE.md` inside each module in `framework/index/modules.json`.

## Principles
- **Short beats long.** One screen per `CLAUDE.md`. Signal over boilerplate.
- **Hard caps.** Module `CLAUDE.md` ≤ 80 lines; root ≤ 150 lines. Every
  `CLAUDE.md` ends up in `claude_md_context` on every review and task
  invocation, so length multiplies across runs. The templates enforce a
  15-symbol cap on `public_api` and a 10-item cap on `notes`; reviewers
  that need more should use Serena (`find_symbol`) or read the inventory
  directly.
- **Describe invariants, not code.** If it is visible in the code, don't
  repeat. If it isn't (why a boundary exists, why this pattern), record it.
- **Link, don't copy.** Point at ADRs, entry files, the inventory.

## Inputs
- `framework/index/inventory.json`
- `framework/index/modules.json`
- `docs/adr/*.md` (may be absent)
- Templates under `framework/core/templates/`:
  - `CLAUDE.md.j2` (root)
  - `module-CLAUDE.md.j2` (per-module)
- Skill: `framework/core/skills/module-writer.py` renders both.

## Steps

1. **Preconditions.** Abort if either index JSON is missing.

2. **Resolve doc filenames.** Before rendering, the skill runs
   `_resolve_doc_filenames()`: if two modules share a path (e.g. a
   C# Build.cs module and a Python helpers module in the same directory),
   the first keeps `CLAUDE.md`; the second gets `CLAUDE.<language>.md`.
   The chosen filename is persisted back into `modules.json:doc_filename`
   so future runs stay stable.

3. **Root `CLAUDE.md`.** Compose context:
   - `project_name` from `package.json` / `Cargo.toml` / `pyproject.toml`,
     else the repo directory name.
   - `languages` from `inventory.structural.languages`, sorted by line
     count descending.
   - Module table: `{name, path, language, public_api_count, depends_on}`.
   - ADR index from `docs/adr/`, sorted numerically.
   - Conventions collected from config files present on disk
     (`.editorconfig`, `.prettierrc`, `ruff.toml`, etc.). Do not invent.

4. **Module `CLAUDE.md`.** Per module: name, path, language, entry file,
   `public_api` (one line per symbol + signature if available),
   `depends_on` / `depended_by`, an empty manual block placeholder, and
   ADRs whose body mentions this module's name or path.

5. **Preserve manual edits.** Before overwriting any `CLAUDE.md`, extract
   the block between `<!-- BEGIN: manual -->` and `<!-- END: manual -->`,
   pass it through as `manual_block`, and render it back verbatim.

6. **Verify.** Runs after all files are written; gate for the hash update:
   - Every module has its resolved `CLAUDE.md` on disk.
   - The root `CLAUDE.md` mentions every module.
   - Every ADR in `docs/adr/` is referenced from root or at least one
     module `CLAUDE.md`.
   - On failure, return non-zero and **do not update
     `framework/index/inventory-hash.json`**, so `--check` catches the
     broken snapshot on the next run.

## Completion signal
Final line:

```
DOCGEN_OK <count> file(s) written
```

## Failure handling
- Template missing — abort, name the expected path.
- Module path absent on disk — warn and skip; continue.
