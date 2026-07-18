# Planning-index eval harness (`planning-eval`)

`core/skills/planning-eval.py` is the **measurement layer** of the planning index
(see `planning_indexer.md`, §"Feedback loop / eval harness" and Rollout step 2).
It is built **metrics-first** — before the query-time retriever (KLC-068) exists —
so the later planning views, edges, roles, and retriever are not tuned blind.

It reads an archived-ticket corpus and writes
`.klc/index/planning/eval_report.json`.

## CLI contract

```text
planning-eval.py --tickets <dir> [--modules <path>] [--repo <path>] [--out <path>]

  --tickets   ticket-archive directory (subdirs, each with meta.json).
              default: $PROJECT_ROOT/.klc/tickets
  --modules   modules.json membership map.
              default: $PROJECT_ROOT/.klc/index/modules.json
  --repo      git repo root for diff derivation + coverage walk.
              default: $PROJECT_ROOT
  --out       report path ('-' for stdout).
              default: $PROJECT_ROOT/.klc/index/planning/eval_report.json
```

Exit codes follow the existing skill convention (`file_scanner.py` /
`dep_graph.py`):

- `0` — ok, **including a degraded run**.
- `2` — bad argument (`--tickets` is not a directory).
- A missing optional source (e.g. `modules.json`) never hard-fails: the affected
  metric section degrades to `status: "unavailable"` and the reason is appended to
  `errors[]`.

`PROJECT_ROOT` comes from the environment.

## Metrics computed now (no retriever required)

- **module-map coverage** — files assigned / total files, from a repo walk with
  baseline excludes (`.git`, `.klc`, `.claude`, build/venv dirs). Reported as
  `coverage.files_assigned / coverage.files_total` and `coverage.coverage_ratio`.
- **orphan rate** — files no module claims / total files
  (`coverage.orphan_rate`), plus `files_shared` (multi-module files).
- **diff → affected-modules precision/recall** — for each archived ticket, its
  git diff's touched files are resolved to modules and compared to the ticket's
  recorded `meta.affected_modules`. Aggregated as `mean_precision`,
  `mean_recall`, `micro_precision`, `micro_recall`, with a per-ticket breakdown
  (`truth` / `computed` / `matched` / `missed` / `extra`).

Membership resolution goes **only** through
`core/skills/module_membership.file_to_module` (the single KLC-066 resolver).
No private longest-prefix matcher is reintroduced — that would recreate the #1
risk `planning_indexer.md` names, a second divergent module set. A shared /
out-of-path file contributes every module in its `member_of`, so it is never
stranded.

### How a ticket's diff is derived

1. **Stored-patch seam — AUTHORITATIVE (the production / offline / CI path):** if
   the ticket dir carries a `*.patch` / `*.diff` or a `changed_files.txt`, those
   files are used. **For authoritative recall/precision metrics, the corpus should
   carry stored patches per ticket** — this is the deterministic, caveat-free
   source, and the one to prefer when a corpus is evaluated repeatedly.
2. **Git history — BEST-EFFORT (convenience fallback):** otherwise
   `git log --grep=<KEY>` (word-bounded, so `KLC-05` does not collide with
   `KLC-051`) over `--repo`. This is heuristic — see the enumerated caveats below;
   treat its numbers as indicative, not authoritative.

**Every scored ticket is tagged with its derivation** so a consumer knows which
numbers to trust: each `per_ticket` entry carries `derivation_source`
(`stored-patch` | `git-log-grep`) and `derivation_confidence` (`authoritative` |
`best-effort`), and `diff_affected_modules` carries `authoritative_tickets` /
`best_effort_tickets` counts plus a `note`. Prefer a corpus where
`authoritative_tickets == tickets`.

The fixture test drives the git-log path directly (synthetic commits with
key-prefixed subjects) and drives the stored-patch path via dedicated tickets
that supply a `changed_files.txt` / `*.patch`.

**Data-source validation.** If `--repo` is not a git checkout, or the coverage
walk yields zero files, the coverage **and** diff sections degrade to
`status: "unavailable"` with a reason in `errors[]` — a bad data source is never
reported as a valid `ok` section full of zeros.

**Git-derivation caveats** (why the stored-patch seam is the deterministic
production path):

- `git log --grep=<KEY>` attributes by commit-message text; a commit that
  *mentions* another ticket's key is attributed there too, and a squash / PR
  merge that drops the key from the subject yields **no** derivable diff.
- **Merge commits:** `git log --name-only` suppresses merge diffs, so a key that
  lands only on a `--no-ff` merge would otherwise derive no files. The harness
  adds each matched merge's **first-parent** diff (`<sha>^..<sha>` — the files it
  integrated into the target branch), so merge-only tickets are scored with their
  real footprint. A large merge can still over-attribute (it brings in everything
  it integrated), which is why the live path is best-effort.
- **Two empty-footprint causes are kept distinct** (they mean different things):
  - **No diff source** — no matching commit *and* no stored patch. This is a
    derivation gap, not an index-quality miss: the ticket is routed to
    `corpus.tickets_skipped` (reason `no matching commits / no stored patch`),
    never scored `0/0`, so it cannot silently drag down `mean_*` / `micro_*`.
  - **Source present, all paths excluded** — the key *is* in history (or a stored
    patch exists) but every changed path is lifecycle/VCS churn (`.klc/**`). The
    ticket's real code footprint is genuinely empty, so this is a **real 0-recall
    evaluation**: it is **scored** with `computed=[]` (recall 0 against the
    non-empty recorded modules; precision 1.0 by convention — no false positives),
    NOT hidden. A documented 0-recall case must stay visible in the metrics.
- `--all` is used so unmerged refs are searched; on a repo with many topic
  branches this can widen attribution. Prefer the stored-patch seam for a
  reproducible corpus.

Lifecycle churn (`.klc/**`) and VCS metadata are excluded from a ticket's
computed module set, so a ticket's own artifact commits do not inflate it.

## Retriever seam (populated by KLC-068)

The retrieval-based metrics — `recall_at_5`, `recall_at_10`, `precision_at_10`,
and `mean_files_before_first_edit` — are a **documented seam**, not a stub:

- when a ticket carries a `retrieval_trace.json` (a `files_to_read_first`
  candidate ranking), the metric is computed against the files the ticket
  actually changed;
- when no usable trace exists in the corpus, `retrieval_metrics.status` is
  `"unavailable"` with a reason, and the run still exits `0`.

The retrieval-metric **keys** (`recall_at_5`, `recall_at_10`, `precision_at_10`,
`mean_files_before_first_edit`) and the status-gated contract are stable across
both states — `null` under `status: "unavailable"`, numeric under `status: "ok"`.
KLC-068 populates the per-ticket traces and adds no schema.

### Reproducibility

`generated_at` is wall-clock by default. Set `SOURCE_DATE_EPOCH` (seconds) to make
it deterministic, so two runs over the same corpus produce byte-identical reports.

## Report shape

```text
{
  schema_version, generated_at, tickets_root, repo,
  corpus:   { tickets_total, tickets_evaluated, tickets_skipped[] },
  coverage: { status, files_total, files_assigned, files_orphan,
              files_shared, coverage_ratio, orphan_rate },
  diff_affected_modules: { status, mean_precision, mean_recall,
                           micro_precision, micro_recall, tickets,
                           authoritative_tickets, best_effort_tickets, note,
                           per_ticket[ { ..., derivation_source,
                                         derivation_confidence } ] },
  retrieval_metrics:     { status, recall_at_5, recall_at_10,
                           precision_at_10, mean_files_before_first_edit,
                           per_ticket[] },
  errors: []
}
```
