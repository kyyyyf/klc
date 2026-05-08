# Periodic Agent

## Role
Keep the index and `CLAUDE.md` tree in sync with the codebase
**incrementally** — touch only what changed since the last run. Designed
for cron, a git hook, or CI.

## Inputs
- `framework/.last-run` — last successfully processed git SHA. If
  missing, abort and ask the caller to run `init`.
- Current `HEAD`.
- Existing `framework/index/inventory.json` and
  `framework/index/modules.json`.

## Steps

1. **Change window.** `LAST = cat framework/.last-run`,
   `HEAD = git rev-parse HEAD`. If equal → `PERIODIC_NOOP`, exit 0.
   Otherwise `git diff --name-only --diff-filter=ACMRD $LAST $HEAD`.
   If the diff covers > 20 % of tracked files, fall back to a full
   init and skip the rest.

2. **Files → modules.** Load `modules.json`. For each changed file, find
   the module whose `path` is the longest prefix. Files that belong to
   no module are recorded under `notes: unassigned change` and
   processing continues.

3. **Closure.** Affected set = directly-affected ∪ transitively
   dependent modules (walk `depended_by`). If closure covers > 50 %
   of modules, fall back to a full init.

4. **Reindex.** For each affected module:
   - On **large projects** use Serena
     (`didChangeWatchedFiles` / module-scoped `find_symbol`) to refresh
     that module's symbol set. On small projects a module-scoped
     ast-grep sweep is fine.
   - Recompute the module's public API with the decompose rules. If it
     changed, flag `public_api_changed` on the module.

5. **Update indices.** Patch module entries in `modules.json` and the
   file-scoped entries in `inventory.symbols`. Refresh `generated_at`
   and `git_sha` in both.

6. **Regenerate docs.**
   - Per affected module → regenerate `<path>/<doc_filename>`
     (preserve manual blocks).
   - If any module has `public_api_changed` or the module set itself
     changed → regenerate the root `CLAUDE.md`.

7. **Commit the baseline.** Write `HEAD` to `framework/.last-run` **only
   after** all updates succeeded. Print a summary (affected modules,
   public-API breakages, files touched). Final line:

   ```
   PERIODIC_OK <N> modules updated
   ```

## Failure handling
- Serena call fails → keep the old index, do **not** advance `.last-run`,
  print `PERIODIC_FAIL <reason>`, exit 1.
- Empty diff but `LAST != HEAD` (merge with no file changes) → advance
  `.last-run`, print `PERIODIC_NOOP`.

## Cron hook
```cron
0 */6 * * * cd /path/to/project && ./framework/scripts/update.sh >> framework/logs/update.log 2>&1
```
