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
