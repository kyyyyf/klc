# Requirements coverage taxonomy — what every draft spec is interrogated against

This is KLC's **requirements-coverage taxonomy**: the single, stable list of
categories a draft spec is checked against for completeness. It answers one
question — "what did we forget to ask about?" — by naming the recurring facets a
specification tends to leave thin: scope, data, interaction, non-functional
qualities, integrations, edge cases, constraints, terminology, completion, and
loose ends.

It is the front-half counterpart to the constitution. Where the constitution
anchors *spec review* (is this change conformant?), this taxonomy anchors *spec
elicitation* (is this change fully specified?). It is the epic root (E-01) that
the elicitation skill (E-02) and the coverage gate (E-05) both read, so
completeness is by construction rather than by luck.

## Provenance

- The **ten categories** are [spec-kit's `/clarify` coverage taxonomy](https://github.com/github/spec-kit)
  adopted verbatim in meaning. spec-kit drives its clarification questions off this
  fixed list — scan each category Clear / Partial / Missing, prioritise by
  Impact × Uncertainty, ask at most a handful with a recommended default.
- The **non-functional category is expanded** via [ISO/IEC 25010](https://iso25000.com/index.php/en/iso-25000-standards/iso-25010)'s
  eight product-quality characteristics, so the otherwise-vague "non-functional"
  bucket carries a named sub-taxonomy instead of a single vague line.
- **Adversarial / abuse** concerns live as a sub-check under `edge-failure`, and
  **security** under `nfr` — deliberately *not* an eleventh top-level category
  (see the spec's open question Q-001). The taxonomy ships the faithful ten.

## Two coupled forms

- **This narrative** (`docs/coverage-taxonomy.md`) — the human-readable rationale
  for each category and its facets.
- **The machine form** (`config/coverage-taxonomy.yml`) — one entry per category:
  `{ id, name, description, min_track, sub_checks }`, with the `nfr` category also
  carrying `sub_characteristics`. `core/skills/coverage_taxonomy.py` is the one
  reader that loads it; a project override at `.klc/config/coverage-taxonomy.yml`
  shadows the framework copy, exactly like `config/models.yml`.

The two are kept in **lockstep**: `tests/test_coverage_taxonomy.py` asserts that
every id in the YAML appears as a heading here and vice-versa, so the two forms
can never drift apart.

## How to read each entry

Every category below is a level-3 heading holding its **stable id** in backticks,
followed by its **min_track** floor and its one-line description, then the facets
(`sub_checks`) a consumer scans within it.

The **min_track floor** is the lightest track (XS / S / M / L) at which coverage
of that category is expected. A consumer asks about a category only when the
ticket's track is at or above the floor: `coverage_taxonomy.for_track(track)`
returns exactly the categories whose floor is at or below the requested track.
The floors follow the epic's track-applicability table — trivial changes (XS) are
only held to scope, completion, and loose ends, while the heavier structural and
quality categories (data model, NFR, integrations, constraints, terminology) come
into force from S or M upward. Ids are **stable once shipped**: E-02 and E-05
reference categories by id, so a rename is a breaking change.

---

## The ten categories

### `functional-scope`

- **min_track** XS
- Core user goals, success criteria, explicit out-of-scope, and actor roles.

The irreducible floor. Even the smallest change must say what it is for, how we
know it worked, what it deliberately does *not* do, and who acts in it. Facets:
`core-goals`, `success-criteria`, `out-of-scope`, `actor-roles`.

### `domain-data-model`

- **min_track** S
- Entities, attributes, relationships, identity, lifecycle states, and scale.

Once a change touches persisted or structured data it must name the entities, how
they are uniquely identified, how they relate, what states they move through, and
at what scale. Missing identity or lifecycle rules are a classic late-breaking
defect. Facets: `entities`, `attributes`, `relationships`, `identity-uniqueness`,
`lifecycle-states`, `data-scale`.

### `interaction-ux`

- **min_track** S
- Primary user flows, inputs and outputs, error and empty states, and accessibility.

How a user (or caller) actually drives the feature: the happy-path flow, the exact
inputs and outputs, and — the parts specs routinely omit — the error and empty
states and accessibility. Facets: `primary-flows`, `inputs-outputs`,
`error-states`, `empty-states`, `accessibility`.

### `nfr`

- **min_track** M
- Quality attributes expanded via ISO/IEC 25010's eight characteristics, with
  measurable targets.

The non-functional bucket, made concrete. Rather than a single vague "must be
fast and reliable" line, this category expands into the eight ISO/IEC 25010
product-quality characteristics and demands measurable targets and observability.
Facets: `measurable-targets`, `observability`.

The eight **ISO/IEC 25010 quality characteristics** (the `sub_characteristics`):

- `functional-suitability` — does it do what is needed, correctly and completely?
- `performance-efficiency` — time behaviour, resource use, capacity.
- `compatibility` — co-existence and interoperability with other systems.
- `usability` — learnability, operability, accessibility, error protection.
- `reliability` — maturity, availability, fault tolerance, recoverability.
- `security` — confidentiality, integrity, authenticity, accountability.
- `maintainability` — modularity, reusability, analysability, testability.
- `portability` — adaptability, installability, replaceability.

### `integration-external`

- **min_track** M
- External services, data contracts, failure modes of dependencies, and versioning.

Where the feature meets systems it does not own: which external APIs it calls, the
data contracts it depends on, what happens when a dependency fails or changes, and
how versions are handled. Facets: `external-apis`, `data-contracts`,
`dependency-failure-modes`, `versioning`.

### `edge-failure`

- **min_track** S
- Boundary conditions, error handling, adversarial and abuse cases, and recovery.

The cases that break naive implementations: boundary values, error handling, and
— folded in here rather than split into a separate top-level category —
adversarial and abuse inputs, plus recovery and rollback. Facets:
`boundary-conditions`, `error-handling`, `abuse-adversarial`, `recovery-rollback`.

### `constraints-tradeoffs`

- **min_track** M
- Technical and business constraints, explicit tradeoffs, and load-bearing assumptions.

The boundaries the solution must respect and the choices it makes within them:
technical and business constraints, the tradeoffs taken deliberately, and the
assumptions the design leans on. An unstated assumption is a silent risk. Facets:
`technical-constraints`, `business-constraints`, `explicit-tradeoffs`,
`assumptions`.

### `terminology`

- **min_track** M
- Defined terms, consistent naming, and a glossary that removes ambiguity.

Ambiguous or inconsistent vocabulary is a spec defect. This category asks that key
terms are defined, named consistently throughout, and collected where a reader can
find them. Facets: `defined-terms`, `consistent-naming`, `glossary`.

### `completion-signals`

- **min_track** XS
- Done criteria and acceptance signals that say when the work is finished.

Every change, however small, must say when it is *done*: the completion criteria
and the acceptance signals a reviewer checks. Facets: `done-criteria`,
`acceptance-signals`.

### `misc-placeholders`

- **min_track** XS
- Open questions, TODO markers, and unresolved placeholders left in the draft.

The catch-all for loose ends: open questions still to be answered, TODO markers,
and placeholder text that must not survive into the final spec. Facets:
`open-questions`, `todo-markers`, `placeholders`.
