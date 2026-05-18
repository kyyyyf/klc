# Periodic Agent

## Role
Keep the index and `CLAUDE.md` tree in sync with the codebase
**incrementally** — touch only what changed since the last run. Designed
for cron, a git hook, or CI.

## Inputs
- `.klc/index/.last-run` — last successfully processed git SHA. If
  missing, abort and ask the caller to run `init`.
- Current `HEAD`.
- Existing `.klc/index/inventory.json` and
  `.klc/index/modules.json`.

## Steps

1. **Change window.** `LAST = cat .klc/index/.last-run`,
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
   - On **large projects** a module-scoped Serena query (typically
     `get_document_symbols` over the changed files only) is the
     cheapest way to see whether the public API shifted. Gate the
     call through `serena-call.py`:

     ```
     serena-call.py check --ticket PERIODIC \
       --track L --phase build \
       --op get_document_symbols --subject <module-path> --file <file>
     ```

     Treat `PERIODIC` as a synthetic ticket id; the call log and cache
     live at `.klc/tickets/PERIODIC/` and survive across runs.
   - On small projects a module-scoped ast-grep sweep is fine; no
     Serena needed.
   - Recompute the module's public API with the decompose rules. If it
     changed, flag `public_api_changed` on the module.

5. **Update indices.** Patch module entries in `modules.json` and the
   file-scoped entries in `inventory.symbols`. Refresh `generated_at`
   and `git_sha` in both.
   - Re-run `core/skills/public-api-filter.py`. It trims the
     (possibly updated) `public_api`, rewrites
     `.klc/index/symbols_by_module.json`, and refreshes
     `.klc/index/per-module-hash.json` so the next differential diff
     has a consistent baseline. Skipping this step causes
     `context-loader` and docgen to read stale per-module slices.

6. **Differential regeneration.** Ask the hash skill which modules
   actually moved:

   ```
   python3 core/skills/per_module_hash.py diff
   ```

   Output shape: `{"changed": [...], "added": [...], "removed": [...]}`.
   Merge the three lists and pass them to the module writer:

   ```
   python3 core/skills/module-writer.py --only <name1,name2,...>
   ```

   The writer always regenerates the root `CLAUDE.md` and validates the
   whole tree; it regenerates per-module CLAUDE.md only for the named
   set. When the list is empty (nothing semantically changed; files
   moved without touching `public_api`), run
   `module-writer.py --root` instead — no per-module work needed.

7a. **Serena denylist harvest (optional).** Periodic is the natural
    pulse for looking at which Serena queries recurred across tickets:

    ```
    python3 core/skills/serena_deny.py propose --min-tickets 2
    ```

    The skill prints candidate regex entries that recurred in two or
    more tickets and are not already covered. Nothing is added
    automatically — surface the suggestions to a retrospective /
    human, and if any are truly noise, add them with
    `serena_deny.py add --pattern ... --reason ...`. Lowering the
    signal-to-noise ratio on Serena calls is a slow compounding win.

7b. **Inline-item re-verification (optional).** If the project uses
    inline `[!FACT F-NNN]` / `[!ASSUMPTION A-NNN]` /
    `[!HYPOTHESIS H-NNN]` items with `verified=<date>` attributes,
    sweep the oldest-verified ones on every run:

   ```
   python3 core/skills/items_verify.py scan --top 20
   ```

   The skill refreshes `verified=` on items whose `src` is unchanged
   (`confirmed`), marks items whose `src` moved as
   `verified=stale-<today>` (`needs-review`), and logs every decision
   to `.klc/knowledge/verification-log.jsonl`. It makes no LLM calls;
   items classified `needs-review` are candidates for a human or LLM
   pass on the next ticket cycle.

   Skip this step on small projects or when no artefacts use `[!FACT]`
   headers yet — the scan is cheap (tens of ms) but not free.

8. **Commit the baseline.** Write `HEAD` to `.klc/index/.last-run` **only
   after** all updates succeeded. Print a summary (affected modules,
   public-API breakages, files touched, fact counts if step 7 ran).
   Final line:

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
0 */6 * * * cd /path/to/project && python /opt/klc/scripts/update.py >> .klc/logs/update.log 2>&1
```
