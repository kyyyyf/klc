# klc architecture — key decisions & cross-cutting invariants

This is doc #3 of three: the **why**. For the process and detailed usage see
[`process.md`](process.md); for install and end-to-end scenarios see the root
[`README.md`](../README.md).

klc helps Claude Code work a large codebase without re-reading every file each
turn. It has two moving parts: a **deterministic indexing loop** (no LLM in the
hot path) that produces a stable module map, per-module `CLAUDE.md`, a dependency
graph, and a stale tracker; and a **data-driven ticket lifecycle** (`config/phases.yml`)
that walks work from intake to archive. This document records the decisions that
shaped both and the invariants that hold across every phase.

---

## Key decisions

### Prompt-driven, not hard-coded (C-001)

Every artefact — spec, test-plan, design, code, review — is produced by an LLM
agent reading a **prompt file** (`core/agents/*.md`), never by branching logic
buried in the state machine. The orchestrator's job is to resolve which prompt +
model runs at each phase (`phase_resolver.resolve_phase`) and to route the
structured completion signal; it does not encode the work itself. The consequence
that recurs everywhere: a capability that a prompt *claims* must be backed by real
wiring, and the doc-honesty tests exist to catch prose that outruns the wire.

This is why interactive phases (clarify gates, ambiguous picks) can only run from
the Claude Code main-loop or a Task-tool subagent — the headless Python driver
(`runner.py`) is forbidden from touching them.

### The generic `ReviewKind` seam

Independent, adversarial review of an artefact — spec, test-plan, impl-plan — is
one mechanism, not three. `core/skills/spec_review.py` is parameterised by a
`ReviewKind` descriptor (reviewer prompt · artifact · output file · its own
`finding_categories` / `decision_topics`). `validate()` reads the vocabulary FROM
the active kind and `route_decisions()` labels advisories with `kind.name`, so
each reviewer (`SPEC_REVIEW`, `TEST_PLAN_REVIEW`, `IMPL_PLAN_REVIEW`) reuses the
SAME parse / validate / route / record / track-scale plumbing with its own
classes — no second copy, no validator fork. Adding a reviewer is adding a
descriptor and a prompt, not a pipeline.

### git-as-CAS ticket state on `klc-state`

Ticket lifecycle state (`meta.json`, artifacts) is not kept on `main`. It lives on
a dedicated `klc-state` branch materialised as a `.klc/` worktree, and every state
transition rides an `acquire_lock → state_tx` envelope that commits and
compare-and-swap (CAS) pushes the ticket subtree to the bound upstream. Feature-ON,
a peer sees a just-committed change with no extra ack; feature-OFF, `state_tx` is a
no-op and writes are plain local edits. Keeping state off `main` is what lets
multi-user coordination be a git property (CAS on push) rather than a new database.

### Dual-remote: origin is real history, gh is a scrubbed public mirror

The repo has two remotes that play **different** roles — they are not two peers
holding an identical `main`. `origin` (GitLab) is the real history and the active
dev/review/merge remote; `gh` (GitHub) is a clean public mirror produced by a
re-authored, content-scrubbed force-push and takes no pull requests. The two mains
hold the same content under different identity and history — **intentionally
divergent lineages**, not fast-forwards of each other. The scrub denylist lives in
the origin-side mirror tooling, deliberately NOT in the constitution, because a
denylist committed onto the surface it guards would both ship the internal tokens
to the public mirror and self-trip any gh-side grep. See
[`constitution.md`](constitution.md) principles `divergent-public-mirror` and
`public-mirror-no-internal-refs`, and the workflow section in
[`process.md`](process.md#dual-remote-workflow).

### plugin-gen as derivation, not a hand-maintained copy

The whole `klc-plugin/` tree — agents, passthrough skills, command stubs,
`.claude-plugin/plugin.json` — is **derived** from source by
`core/skills/plugin_gen.py`; nothing under `klc-plugin/` is hand-maintained. As
of KLC-113 that derivation is a genuine transformation, not a verbatim copy: a
`core/agents/*.md` source may carry a line-anchored `{{include:<name>}}`
directive, and `generate_agents` expands it against
`core/agents/_includes/<name>.md` while writing the plugin copy — the shared
completion-signal contract and findings-assessment procedure exist once, in
`_includes/`, and are inlined into every prompt that needs them at generation
time. An unresolvable include name raises rather than shipping the literal
directive. The deployed prompt `phase_resolver` serves is the PLUGIN copy
(expanded), so a stale copy means an enrichment never runs. The rule is still
machine-checkable, expansion included: after editing any `core/agents/*.md`
(including `core/agents/_includes/`) or the verb dictionary, run
`python3 core/skills/plugin_gen.py`; the drift-guard
`tests/test_plugin_agents_in_sync.py` regenerates into a temp dir and reddens
on any byte mismatch against the committed tree, and the pre-commit
`plugin_gen.py --check-if-staged` hard-fails the commit.

---

## Cross-cutting invariants

These hold across phases, reviewers, and gates. They are the shared safety
posture; a new feature is expected to preserve all of them.

- **degrade-not-fail.** A missing optional input never crashes a phase. An absent
  constitution / self-check / reviewer output — or a valid-JSON-but-wrong-shape
  verdict — degrades to a single surfaced note; the phase still completes. The
  planning-eval harness applies the same rule: a missing `modules.json` degrades
  the affected section to `status: "unavailable"` and exits `0`, never a valid-
  looking section full of zeros.
- **no-fork.** Reuse the single source, never a private second copy. Membership
  resolves only through `module_membership.file_to_module`; review vocabularies
  live on the `ReviewKind`, not in the caller; the impl-plan step parser is one
  function, `impl_plan_check.extract_step_fields` (KLC-113 — it replaced a
  second, incompatible fork that used to live in `core/skills/artefacts.py`).
  A second divergent copy is the recurring #1 risk.
- **one module vocabulary (KLC-111).** A module name is the `name` of an entry
  in the deterministic `.klc/index/modules.json`, plus the framework/delivery
  paths configured under the `scope.infra_paths` settings knob (default
  `.klc/`, `hooks/`, `.github/`, `.gitlab/`, `README.md`). Nothing else is a
  module name, and no producer or consumer keeps its own private list:
  `module_vocabulary.py` is the one place that answers "is this path infra"
  and "what module name does this path have", wrapping
  `module_membership.file_to_module` exactly once so a gate's decision for a
  file and the scope-guard's decision for that same file can never diverge.
- **fail-open (advisory) vs fail-closed (gates).** The independent reviewers are
  fail-open: they surface and record, they never block the ack. The review
  cascade and gate-policy signals are fail-closed: "unavailable" is treated as
  dirty, and only proven-clean signals let a conditional gate auto-proceed.
- **surface-only / read-only probes.** A read-only probe (`persist=False`, used by
  `klc remind` and gate-policy signal collection) surfaces the same advisories
  WITHOUT writing any `*-review-findings.json`; only the persisting ack path
  records. Read verbs (`klc work`, `klc publish`, `klc status`) take no holder and
  write nothing.
- **one file universe.** `structural.files_rel` — git-tracked intersected with the
  resolved excludes — is the ONLY file universe for index builders. Every skill that
  writes into `.klc/index/` takes its file list from `file_universe.resolve()`; none
  enumerates project files by walking the working tree. The cost is deliberate and
  worth naming: a file is invisible to the index until `git add`. When git is
  unavailable the resolver walks ONCE, marks the source `walk`, and every builder
  consumes that same walked list.

---

## Kept machine-coupled docs

Four docs are deliberately NOT prose to absorb — each is paired with config or a
generator and guarded by a lockstep test, so they stay as their own single
sources. This doc and [`process.md`](process.md) link to them rather than
re-authoring their content:

- [`constitution.md`](constitution.md) — the mandatory, machine-checkable review
  principles; lockstep with `config/constitution.yml` (`test_constitution.py`).
- [`coverage-taxonomy.md`](coverage-taxonomy.md) — the requirement-coverage
  checklist; lockstep with `config/coverage-taxonomy.yml`
  (`test_coverage_taxonomy.py`).
- [`tracks.md`](tracks.md) — the XS/S/M/L decision rubric; GENERATED by
  `gen_tracks_doc.py` and guarded by `test_tracks_drift.py`.
- [`severity-rubric.md`](severity-rubric.md) — the four severity levels every
  review agent cites; referenced by `scripts/review.py` and the review sub-agents.

---

## Map over `docs/adr/`

Architecture Decision Records capture single, dated decisions with their rejected
alternatives. They are written by the `adr` agent and read by `docgen`; the
directory is retained as the operational ADR store.

- [`docs/adr/ADR-001-phase-resolver-two-executors.md`](adr/ADR-001-phase-resolver-two-executors.md)
  — why phase resolution feeds two executors (the CC main-loop for interactive
  phases, the headless `runner.py` for mechanical fan-out) from one
  `resolve_phase` source of truth.

New decisions of lasting architectural weight go here as `ADR-NNN-*.md`; the dated
epic plans under `docs/2026*-*.md` capture larger multi-ticket initiatives.

---

## Call-graph backends (feasibility substrate)

Feasibility and impact checks lean on a language-specific call graph at
`.klc/index/callgraph/<lang>.json` (schema
`{symbols: {id: {kind, file, line, calls, called_by}}}`). `scripts/review.py`
slices the graph for the changed files and passes it to the review agents.

| Language | Backend | Script |
|----------|---------|--------|
| Python | Static AST (`ast` module) | `core/skills/callgraph_python.py` |
| Rust | rust-analyzer LSP | `core/skills/callgraph_rust_async.py` |
| C++ | clangd LSP (default) | `core/skills/callgraph_cpp.py` |

The C++ backend queries the translation units in `compile_commands.json` plus
project-tree headers, resolves virtual-override edges best-effort via
`goToImplementation`, and offers a query mode (`--query references|workspace-symbol`)
that returns `file:line` locations without loading source into the caller's
context. A pre-built on-disk SCIP index (`scip-clang`) is a documented future
option for large repos where clangd cold-start is too slow — a CI/cache decision,
not implemented.

---

## Index-coverage verdicts (degrade honestly, KLC-106)

Every index builder — the dependency-graph producers, the inventory, the
callgraph builders — accepted an external tool's output the moment the process
exited 0 and the JSON parsed, with no check that the output actually covered the
project. `core/skills/index_coverage.py` is the one shared, language- and
tool-agnostic module that answers "did my output actually cover the code?": a
builder hands it an observed count and a universe count (usually
`structural.languages[<lang>].files`, or `structural.total_files` for a
language-agnostic producer), and it returns a verdict record
`{builder, artifact, metric, observed, universe, ratio, threshold, degraded,
reason}`. Below the coverage threshold — `index.coverage.min_ratio` in
`config/settings.yml`, default `0.25`, with an optional
`index.coverage.per_builder.<name>` override, both settings-only knobs with no
legacy file — the builder stamps `degraded: true` and a human-readable `reason`
on its own artifact and appends the verdict to that artifact's `errors[]`.

The verdict travels **with** the artifact rather than into a second file: a
consumer that already opens `depgraph.json` or `inventory.json` cannot be honest
by accident and dishonest by omission. `module_edges`, `symbol_usage` and
`test_map` each add their own `degraded_inputs: [...]` list naming every upstream
artifact that is degraded or vacuous, and `planning-retriever.build_trace` caps
`confidence` at `low` — at every site that produces one, not only the top-level
field — whenever that list is non-empty, and reports `mode: "name-match-only"`
when its module ranking rested on name/path matches alone because
`module_edges` contributed no edges. `dep_graph.build` also uses the same verdict
to decide which of two candidate graphs for one language to keep: the richer
node-coverage ratio wins, ties break on edge count, and the discarded
candidate's tool name and ratio land in `errors[]` — a poorer external-tool
result can no longer silently overwrite a richer generic-scanner one.

Presentation is a **derived** view, never a second authority:
`index_coverage.collect_verdicts(index_dir)` harvests every persisted verdict
from the artifacts' own `errors[]` at read time, for the root `CLAUDE.md`'s
"Notes from the indexer" section, the per-builder summary line `klc init` and
`klc update` print on every run, and `klc doctor`'s warn-only `index-degraded`
check (`core/phases/doctor.py`; `index_health.py` is the module that computes
it, not the check's registered name). There is no `index_health.json`;
escalating a degraded index to a hard failure, and detecting staleness, are
KLC-107's.

**The inventory cap is language-scoped, not whole-artifact (KLC-123).**
`inventory.json` carries one coverage verdict PER LANGUAGE (via
`deterministic_inventory.inventory_coverage_verdicts`), but the retriever's
own cap used to fold ALL of them into a single flat pass/fail with
`artifact_degraded` — one repo-wide minority language with no rule set (this
framework's own `.h` fixtures, classified as `c`, 0 files with symbols) forced
`confidence: low` on every trace, regardless of which languages that trace's
own evidence actually touched. `index_coverage.scoped_inventory_degradation
(inventory, candidate_languages)` replaces that whole-artifact OR with a
language-scoped decision: a degraded language caps only when it is relevant
to THIS trace — one of `planning-retriever.build_trace`'s own candidate
languages, or, when no candidate files are known, one of the repo's dominant
languages by share of the code universe (the
`index.coverage.language_share_threshold` settings knob, default `0.05`). A
degraded language outside that relevance set never caps; it surfaces as an
additive `coverage_advisories` entry on the trace instead (naming the
language and its share), an `info`-level honesty signal that never
participates in `_cap_confidence`'s decision. An inventory built before this
change (no per-language verdicts in `errors[]`) falls back to the original,
unscoped `artifact_degraded` check unchanged.

**`candidate_languages` is scoped to the trace's PRESENTED slices, not every
matched file (KLC-123 step-5, D-123-4).** The first cut derived
`candidate_languages` from every file that merely scored `> 0` during
matching, which re-admitted a narrower version of the same over-reach this
section exists to fix: a file that only weak-matches a query token through
its path (e.g. an orphaned fixture that shares a directory-name token with
the query, never read or edited for that query) could still drag its
language into scope and cap confidence. `build_trace` now resolves module
selection and both presented slices — `files_to_read_first` and
`files_likely_to_edit` — first, then computes `candidate_languages` from
`set(files_to_read_first) | set(files_likely_to_edit)` (via
`_candidate_languages(paths)`, `file_scanner.EXT_LANG` still the map used to
classify each path's extension) **before** `trace_degraded_inputs` is
assembled; the loop that produces each module's confidence value still runs
strictly after `trace_degraded_inputs` is known, so KLC-106 D-204's ordering
constraint (no confidence value produced before the degraded-inputs list is
final) is preserved — only module/file *selection*, never a confidence
value, moved earlier. Practically: a weak path-token collision on a file
that never lands in either presented slice (e.g. it belongs to no module, or
its module isn't selected) never enters `candidate_languages` and never caps
confidence — it is invisible to the cap, not merely advisory. The same
collision on a file that DOES land in a presented slice (its module is
selected and the file is `eligible_as_primary`) still caps, because the
reader is being told to read or edit that file.

`file_scanner.EXT_LANG` is now cross-checked against the active profile's
`sgconfig.yml` (KLC-124): the two tables used to disagree on `.h`
(`EXT_LANG` said `c`, `sgconfig.yml`'s `languageGlobs` said `cpp`), which
manufactured exactly the kind of permanently-uncovered, phantom minority
language this section describes on every repo with C++ headers.
`file_scanner.ext_lang_sgconfig_disagreements` is the one comparator both a
mechanical test and a warn-only `klc doctor` check consult, so the `c`/`cpp`
header split cannot silently drift apart again.

---

## Per-file fingerprints and the full-rebuild decision (KLC-121)

`structural.json` publishes a `files` map: one SHA-256 digest and byte size
per member of `files_rel`, alongside the scalars `schema_version`,
`fingerprint_algo` and `profile_identity`. It is the substrate a later
incremental merge will consume — KLC-125 is the ticket that adds that
merge. Nothing consumes it to skip work today: every refresh is still a full rebuild, and every run says so in one line.

The fingerprints and the fallback are keyed by path and the recorded digest
only. They never branch on a file extension, a language or an external
tool, so a repository in a language klc has no extractor for is
fingerprinted exactly like any other (`core/skills/index_fingerprint.py` is
the one module a static test polices for this).

A run rebuilds everything and names one of seven reasons, in this
precedence: the `--full` flag, the previous artifact being absent, it being
unparseable, or a change in `schema_version`, `fingerprint_algo`,
`files_rel_source` or the resolved profile identity. `klc update --full`
also runs when `HEAD` has not moved since the last run, because asking for
a full rebuild is asking for one to happen; `klc update --force` keeps its
separate meaning of running an unmoved `HEAD` through the ordinary
fingerprint comparison. The two flags are independent, and combining them
is well defined. When none of the seven fired, the line reads `full
rebuild (incremental merge not yet implemented — KLC-125)`, because a line
that reads like a skip when nothing was skipped is the defect this section
exists to prevent.

The profile that a run resolves is also handed to every child builder
exactly once, through `core/skills/profile_cache.py` and the
`KLC_PROFILE_PAYLOAD` environment variable (`profile_cache.run_scope()`).
This closed thirteen separate `profile-resolve.py` spawns per run down to
one, and removed the correctness hazard of one run's artifacts being built
against two different profile reads. Every builder still resolves the
profile itself when run standalone from a shell — the handoff is an
optimisation the run performs, never a precondition a builder may assume.

## Planning-index evaluation (measurement before tuning)

`core/skills/planning-eval.py` is the **measurement layer** of the planning index,
built metrics-first — before the query-time retriever exists — so the later
planning views, edges, and retriever are not tuned blind. It reads an
archived-ticket corpus and writes `.klc/index/planning/eval_report.json` with:
module-map coverage, orphan rate, and **diff → affected-modules precision/recall**
(each archived ticket's diff resolved to modules and compared against its recorded
`meta.affected_modules`). The retrieval metrics (`recall_at_5`, `recall_at_10`,
`precision_at_10`, `mean_files_before_first_edit`) are a documented, status-gated
seam: numeric under `status: "ok"`, `null` under `status: "unavailable"`.

A ticket's diff is derived from an **authoritative** stored-patch seam
(`*.patch` / `changed_files.txt`) when present, else a **best-effort** `git log
--grep=<KEY>` fallback; every scored ticket is tagged with its `derivation_source`
and `derivation_confidence` so a consumer knows which numbers to trust. This is the
`degrade-not-fail` invariant applied to metrics: a bad data source is reported as
`unavailable`, never as a valid section of zeros.

`planning-eval.py` was, until KLC-110, a standalone CLI with no caller anywhere in
the lifecycle: a retrieval trace was written for every ticket at intake, the
committed diff was computable at integrate, and nobody ever compared the two.
KLC-110 closes that loop at the point both ends are already available — the
integrate ack, reusing the KLC-096 report-only advisory precedent. A third
advisory producer (`phase_completion._retrieval_advisories`, beside the two
drift producers) evaluates the ticket's trace against
`phase_completion._committed()`'s own committed-diff pair (the same ground truth
drift-check reports on, so the two can never disagree about what a ticket
changed), through the ONE canonical `rank_metrics` this scorer exposes
(`retrieval_eval.load_planning_eval()`, KLC-110 D-213). The record lands in
`meta.json:metrics.retrieval` — staged onto the ack's own transaction so a
rolled-back push leaves no record — and a JSON line is appended to the derived,
never-tracked `.klc/knowledge/retrieval-eval.jsonl`. `klc metrics --rollup`
aggregates the per-ticket records into a `retrieval` sub-block under each
`per_track.<track>` entry and a top-level `per_confidence` block keyed by the
trace's own claimed confidence, so a *confidently wrong* retriever — `high` or
`medium` confidence with zero edit-slice precision — is a named,
machine-readable signature (`per_confidence.high.retrieval.zero_precision_at_5_tickets`) —
that list also names a ticket whose edit-slice precision is null (an empty
`files_likely_to_edit`, not a scored zero), since both readings are equally a
retriever that named nothing useful. The whole addition is
report-only: it never blocks an ack, never raises, and a read-only probe
persists nothing (the same invariants KLC-096 established for drift-check).
`planning-eval.py --backfill` runs the same scorer offline over the whole
ticket corpus — both the `stored` traces written at intake and `replayed`
traces re-run against the current index — and renders the pre-KLC-108 baseline
table this repository's numbers are compared against going forward
(`docs/20260920_klc110-retrieval-baseline.md`).

## Retrieval scoring (KLC-108)

The retriever's precision problem had two independent causes: the symbol index
carried mostly function-body locals, and the module score was an unnormalised
sum that always favoured the biggest directory. KLC-108 fixed both, then made
the confidence label mean something.

**The rules capture top-level declarations only.** Every rule file under
`core/rules` states `not: {inside: {kind: <the language's function-body node>,
stopBy: end}}` and proves it with an executed `invalid` case that places the
captured declaration form inside a function or method body
(`tests.rule_test_executor.run_rule_tests`, the same production scan path
`klc init` uses). `stopBy: end` is load-bearing: a declaration's immediate AST
parent is a block/statement node, never the enclosing function itself, so a
plain `inside` (no `stopBy`) fails to exclude even a single-level-nested local.
A class's own methods and class-scope constants are not "inside a function
body" and stay captured.

**Keywords are ranked by salience, not the alphabet.** `file_roles.keywords`
is derived from a file's basename tokens (never dropped by the cap), its
top-level symbol names, and the first line of its docstring or leading
comment, then capped at `_KEYWORD_CAP` (12) and ordered by descending inverse
document frequency — the file's OWN name always survives; a repository-common
token is what gets dropped. The IDF table itself
(`.klc/index/token_idf.json`) is built in the same traversal that produces the
keywords, from the pre-cap candidate-token pool, so the two artifacts can
never disagree about their vocabulary: `idf(t) = log((N+1)/(df(t)+1)) + 1`,
rounded to six decimals, strictly positive even for a token in every file. An
index built before this artifact existed still scores — the retriever falls
back to a uniform weight when the table is absent.

**The module score is one stated, size-normalising formula:**

```text
module_score = own_signal + best_file + aggregate / sqrt(n_matched)
```

`own_signal` is the module's own keyword/summary/name match; `best_file` is
the single highest-scoring matched file in the module; `aggregate` is the sum
of every matched file's score; `n_matched` is the COUNT of the module's files
that scored above zero (not the module's total file count), so one genuine
hit inside a 122-file module is not punished for the module's size while the
"many weak hits" bag effect — the defect that made `tests/integration` (122
files) outrank a module that actually matched the query — still is. Every
token's contribution is weighted by its IDF (above), so a token common across
the repository contributes strictly less than a rare one. Design's original
divisor was natural-log damping (`aggregate / log(1 + n_matched)`); measuring
it against the repository's own real worst-case module size showed the bag
still winning (26.35 vs. 24.43 for a genuinely strong single file) — `sqrt`
damping grows faster for large `n` and comfortably reverses that (12.05 vs.
20 at the same scale). Module scores are floats; the ranking key is the score
rounded to six decimals so a last-ulp libm difference between builds cannot
reorder a near-tie and break the trace's byte-stability.

**A module that is mostly tests is never a place to start.** A module whose
`file_roles` records are at least 80% `is_test` (a record with no `is_test`
key counts toward the test side — a malformed record can only keep a module
OUT, never sneak one in) never appears in `primary_modules`; its own tests
still reach `tests_to_read_or_run` through the module-to-tests lookup.

**`confidence: high` requires separation AND a real hit in the edit slice.**
The top module's normalised score must exceed the runner-up's by at least
`_HIGH_SEPARATION_RATIO` (`4.0` — retuned from an initial design estimate of
`2.0` against a real measurement over 110 archived klc tickets, where `2.0`
let 27 of them claim `high` confidence with zero precision on their edit
candidates; `4.0` clears the highest observed false-positive separation
[3.97x] with margin) **and** at least one `files_likely_to_edit` entry must
carry a keyword/symbol (strong) hit; `top <= 0` is floored to `low` before
either condition is even checked, so a query that only surfaces a shared
(cross-module) file — which scores no module directly — can never read as
`high` on the strength of an unrelated edit-slice hit alone
(`[!DECISION D-108-8]`, review round 1). When there is no runner-up, or the
runner-up scores zero, the separation condition counts as met (this still
requires `top > 0`). The trace's `reasons[]` names which of the two
conditions decided the outcome. This is a precondition for `high`, not a
replacement for KLC-106's cap: `_cap_confidence` still forces `low` whenever
an upstream input is degraded or vacuous, regardless of separation or
edit-slice evidence.

**`_HIGH_SEPARATION_RATIO = 4.0` is a calibration on today's corpus, not a
universal constant.** It was chosen as the smallest round value strictly
above the highest false-positive separation observed on the exact 111-ticket
corpus AC-16 is graded against — there is no held-out set. That is legitimate
threshold calibration (design's own assumption A-102 pre-authorized retuning
"in the open, against AC-16 rather than against an impression"), and it is
conservative in one direction only: raising the ratio can only turn a false
`high` into an honest `medium`/`low`, never the reverse, and it does not
touch `precision_at_5`/`recall_at_10` at all (those are pure ranking
numbers, unaffected by the confidence label). But a threshold tuned to zero
violators on the yardstick corpus is calibration only for as long as it is
re-measured: as new tickets accumulate, `4.0` should be re-checked against
AC-16 the same way `2.0` was found wanting, not assumed permanent.

**The yardstick measures the edit slice, not just the read list.**
`planning-eval` reports `precision_at_5` over `files_likely_to_edit` beside
the pre-existing `files_to_read_first` metrics, computed through one shared
`rank_metrics(candidates, truth, k)` scorer (also used for `recall_at_5`,
`recall_at_10` and `precision_at_10`) that returns `precision: null` — never
a fabricated `0` or `1.0` — on an empty candidate list. `--rescore` replays a
ticket's own recorded query against the CURRENT index instead of reading a
stored `retrieval_trace.json` built from an older index vintage, so a BEFORE
run and an AFTER run can cover the same corpus.

**Honest measurement method and numbers (review round 1, replacing the
ticket's original step-8 evidence).** The step-8 build measured AFTER over
the full 110-archived-ticket corpus but used the spec's stale 3-probe-ticket
BEFORE baseline (`0.133`) as the denominator for the `1.5x` bar — comparing
two different corpora, not the same corpus before and after the change. A
follow-up measurement re-derived BEFORE the same way AFTER was measured:
both sides reconstructed in isolated git worktrees (BEFORE at the pre-ticket
commit, AFTER at the shipped commit), scanning the identical file tree, and
scored with the SAME `rank_metrics` function over the SAME 111-ticket corpus
(every archived ticket with a git-recoverable diff) and the SAME
`git_touched`-derived ground truth. The honest numbers: corpus mean
`precision_at_5` rose from `0.196` (BEFORE) to `0.241` (AFTER) — a `1.23x`
gain, which does **not** clear the `1.5x` bar AC-15 states (recorded as
`[!QUESTION Q-108-1] blocks=ack` for the operator, not silently passed or
forced by retuning a scoring constant). Corpus mean `recall_at_10` held at
`0.104` against a `0.088` baseline — AC-15's non-regression clause holds.
Zero tickets report `confidence: high` together with `precision_at_5 == 0`
after the change, against **45 of 111** before it — AC-16 holds, and by a
wide margin, in the specific "confidently wrong" failure mode AC-12/AC-16
target. The original 3-probe subset (KLC-100/101/102) is not wrong on its
own terms — re-extracting it from the honest 111-ticket BEFORE run
reproduces the spec's pinned FACT-table mean (`0.133`) exactly — it is
simply unrepresentative of the OLD retriever's corpus-wide behaviour
(`0.196`, 47% higher), because that retriever's near-blanket `high`
confidence label surfaced edit-slice candidates on nearly every ticket, not
just the ones it was actually right about. The full method, per-ticket data
and the reconciliation table are recorded in
`.klc/tickets/KLC-108/measure/README.md` and
`.klc/tickets/KLC-108/build-log.md`.
