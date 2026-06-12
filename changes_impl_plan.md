# Implementation plan — process changes 1–8

Audience: the implementing agent (Sonnet for changes 2–8; Opus owns the core of change 1).
Date: 2026-06-12. Branch base: `feature/KLC-022-jira-pull` (or a fresh `feature/klc-process-changes-*`).

Contract per step (dogfoods the shipped `design.md` roadmap contract):
**Goal / RED / GREEN / VERIFY / COMMIT / Depends-on.** Behaviour-changing steps need a RED test
first; prompt/config-only steps use `RED: not applicable` + reason.

## Ownership

- **Change 1 core** (triage prompt, confidence model, blast-radius→estimate): **Opus**. Mechanical
  sub-parts (bilingual keywords, `models.yml` downgrade) may be Sonnet.
- **Changes 2,3,4,5,6,7,8**: **Sonnet**, from the steps below.

## Documentation parity (MANDATORY — gates every change)

A change is **not done** until its docs are updated in the SAME commit series. There is no automated
doc-drift guard for `docs/` (only `docgen --check` covers the `CLAUDE.md` tree), so this is a hard
discipline rule. Every change's final step is a `docs:` step that updates the files below and
re-greps for stale claims. A reviewer must reject a change whose docs still describe old behaviour.

| Change | Docs / comments to update |
|--------|---------------------------|
| 1 | `docs/process.md` (intake routing, XS fast-track step 1, Tracks, Discovery context), `docs/tracks.md` (track is provisional; triage; discovery authoritative + blast-radius), `docs/roles.md` (intake), `docs/process-metrics.md` (intake metrics), `config/models.yml` (triage role comment), `core/agents/intake.md` (reconcile: deterministic routing + optional cheap triage, drop stale "intake-agent-pending") |
| 2 | `docs/process-artifacts.md` (spec.md Affected = verified src or assumption) |
| 3 | `docs/process.md` (S path), `docs/tracks.md` (S sequence), `docs/process-artifacts.md` (impl-plan/test-plan provenance for S) |
| 4 | `docs/process.md` (M sequence), `docs/tracks.md` (M sequence), `docs/process-artifacts.md` (detailed tests in impl-plan for M) |
| 5 | `docs/process.md` (review cascade section + new thresholds), `config/reviewers.yml` comments |
| 6 | `docs/process.md` (conditional phases table: learn now mandatory on M/L; ADR-accept in learn), `docs/process-metrics.md` |
| 7 | `docs/process.md` (review / external reviewer default-on + opt-out), `config/reviewers.yml` comments, `docs/roles.md` (reviewer) |
| 8 | `docs/process.md` (review cascade / metrics), `docs/process-metrics.md` (review_depth + cheap-escape-rate) |

Verification for every `docs:` step: `grep` the repo for the old term/behaviour you changed and
confirm no stale description remains (e.g. after change 7, `grep -rn "enabled:.*false" config/reviewers.yml`
and `grep -rni "external.*disabled\|external.*off" docs/`).

## Global sequencing (dependency- and shared-file-aware)

| Order | Change | Why here | Shared files to coordinate |
|------|--------|----------|----------------------------|
| 1 | **2** | tiny; precondition for change-1 blast-radius on XS/S | discovery-lite.md |
| 2 | **1** | biggest; needs change 2 for accurate paths | route_heuristic.py, intake.py, models.yml, discovery.md, discovery-lite.md |
| 3 | **3** | discovery-lite settled after 1/2 | phases.yml, discovery-lite.md, test-planner.md |
| 4 | **4** | shares phases.yml + test-planner.md with 3 | phases.yml, test-planner.md |
| 5 | **5** | independent | review_cascade.py, reviewers.yml |
| 6 | **7** | shares reviewers.yml with 5 | reviewers.yml, review.py, review.md |
| 7 | **6** | learn cluster | phases.yml, retrospective.md |
| 8 | **8** | shares retrospective.md with 6 | review-report.md.j2, retrospective.md, metrics.py |

Run `git commit` per step. Run the framework's tests where they exist:
`python -m pytest tests/ -q` and `python core/skills/validate_config.py` (config changes).
If pytest is unavailable, state so in the build-log and fall back to the per-step manual VERIFY.

---

## Change 2 — `src=path:line` mandatory in discovery-lite

Files: `core/agents/discovery-lite.md`.

**step-1 — harden the Affected contract**
- Goal: remove the "if available" loophole; force fact-or-assumption split.
- RED: not applicable (prompt edit).
- GREEN: in the `## Affected` template line, change
  `<file-or-symbol, with src=path:line from LSP if available>` →
  `<file-or-symbol, src=path:line — LSP-verified, mandatory>`. In rule 3, append: "If LSP cannot
  resolve the path/symbol, do NOT write an unverified module — mark that line
  `[!ASSUMPTION if-false=scope-may-expand]` instead. No third (unanchored) option."
- VERIFY: re-read discovery-lite.md; confirm no remaining "if available"; the assumption mechanism
  is referenced.
- COMMIT: `klc-chg2 step-1: discovery-lite requires LSP-verified src or explicit assumption`
- Depends-on: none.

---

## Change 1 — intake routing B+A + blast-radius in discovery  (Opus owns core)

Files: `core/skills/route_heuristic.py`, `core/phases/intake.py`, `config/models.yml`,
`core/agents/discovery.md`, `core/agents/discovery-lite.md`, (optional new) `core/agents/intake-triage.md`.

**step-1 — confidence + reinterpret length in route_heuristic** *(Opus)*
- Goal: heuristic returns a confidence; short+weak signals = low confidence, length no longer
  lowers the track.
- RED: add `tests/test_route_heuristic_confidence.py` — short ambiguous text → `confidence == "low"`
  and hint not forced down; long/clear text → `confidence == "high"`.
- GREEN: extend `RouteResult` with `confidence`; compute low when word_count < ~30 AND no
  keyword/module signal; length contributes to confidence, not to the floor.
- VERIFY: `python -m pytest tests/test_route_heuristic_confidence.py -q`
- COMMIT: `klc-chg1 step-1: route_heuristic confidence + length reinterpretation`
- Depends-on: none.

**step-2 — bilingual + scope keyword lists** *(Sonnet ok)*
- Goal: stop missing RU tickets and domain/scope terms.
- RED: extend the step-1 test — "поддержать токены доступа только на чтение" → M-signal;
  "светлая тема"/"theme"/"i18n" → not XS.
- GREEN: add RU/EN synonyms + scope terms (theme, тема, i18n, локализация, permissions, права,
  roles, доступ, токены, auth) to `_ML_KEYWORDS`; keep aggregation max-wins.
- VERIFY: pytest the test file.
- COMMIT: `klc-chg1 step-2: bilingual + scope keywords`
- Depends-on: step-1.

**step-3 — cheap triage on short + track ≤ S (B), uncertainty→full discovery (A)** *(Opus)*
- Goal: when short AND mechanical track ≤ S, run a cheap structured triage; on low confidence
  without triage, route to full discovery (skip lite).
- RED: `tests/test_intake_routing.py` — given a short low-confidence ticket and triage disabled,
  intake routes to `discovery` (full), not `discovery-lite`; with triage enabled (stubbed), the
  triage's `provisional_track` is honoured.
- GREEN: add `core/agents/intake-triage.md` (structured output: `{provisional_track,
  hidden_scope_risk, needs_enrichment, missing_info, rationale}`); wire optional invocation in
  `intake.py` gated on (short ∧ track≤S ∧ triage-enabled); when triage off ∧ low confidence → set
  route to full discovery. Record decision in meta (`route_confidence`, `triage_used`).
- VERIFY: pytest the test file.
- COMMIT: `klc-chg1 step-3: cheap triage (B) + uncertainty→full discovery (A)`
- Depends-on: step-1, step-2, change 2.

**step-4 — lower the triage model** *(Sonnet ok)*
- Goal: triage is classification, not deep reasoning.
- RED: not applicable (config).
- GREEN: in `config/models.yml`, point the intake triage role at a cheap role (e.g. `local-simple`),
  NOT `heavy-reasoning`. Document it in the file's comments.
- VERIFY: `python core/skills/validate_config.py`; grep models.yml shows the cheap role.
- COMMIT: `klc-chg1 step-4: intake triage on cheap model`
- Depends-on: step-3.

**step-5 — blast-radius into the estimate (discovery + light discovery-lite)** *(Opus)*
- Goal: discovery reads reverse edges (`depended_by`) and factors blast-radius into risk/complexity.
- RED: not applicable (prompt edit) — but cite the rule explicitly so reviewers can check.
- GREEN: in `discovery.md` add a step before the estimate: read `modules.json`/`depgraph.json`
  `depended_by` for affected modules; large fan-in (e.g. foundational module) raises risk/complexity
  axes. In `discovery-lite.md` add a one-line lightweight version. Reference `change 2`'s verified
  paths.
- VERIFY: manual — re-read both prompts; the estimate section names the reverse-edge input.
- COMMIT: `klc-chg1 step-5: blast-radius (depended_by) into the estimate`
- Depends-on: step-3, change 2.

**step-6 — documentation parity** *(Opus)*
- Goal: docs describe the new routing reality; no stale claims.
- RED: not applicable (docs).
- GREEN: update `docs/process.md` (intake routing, XS fast-track step 1, Tracks, Discovery),
  `docs/tracks.md` (provisional track + triage + authoritative discovery with blast-radius),
  `docs/roles.md` (intake), `docs/process-metrics.md` (intake metrics), `config/models.yml` comment,
  and reconcile `core/agents/intake.md` (deterministic routing + optional cheap triage; drop the
  stale "intake-agent-pending" / heavy-agent narrative).
- VERIFY: `grep -rni "intake-agent-pending\|heavy-reasoning.*intake" .` returns nothing stale; docs
  mention confidence/triage and provisional track.
- COMMIT: `klc-chg1 step-6: docs parity for intake routing`
- Depends-on: steps 1–5.

---

## Change 3 — merge acceptance-test-plan into discovery-lite for S

Files: `config/phases.yml`, `core/agents/discovery-lite.md`, `core/agents/test-planner.md`.

**step-1 — discovery-lite emits S-only test-plan + impl-plan**
- Goal: for S, discovery-lite produces spec.md + acceptance test-plan.md + short impl-plan.md.
- RED: not applicable (prompt edit).
- GREEN: in `discovery-lite.md`, add an **S-only** output section: acceptance AC→test table
  (e2e/acceptance) + short `impl-plan.md` (1–3 steps, the contract from shipped change A/C). XS
  produces neither. Move the short-impl-plan wording out of `test-planner.md` (relocate change C).
- VERIFY: manual — discovery-lite.md gates the extra outputs on `track == S`; test-planner.md no
  longer claims to write impl-plan for S.
- COMMIT: `klc-chg3 step-1: discovery-lite produces S test-plan + impl-plan`
- Depends-on: change 1, change 2 (discovery-lite settled).

**step-2 — phases.yml: acceptance-test-plan → [M,L]; discovery-lite S outputs**
- Goal: drop acceptance-test-plan for S; declare discovery-lite's S outputs.
- RED: not applicable (config) — guarded by VERIFY tests.
- GREEN: set `acceptance-test-plan.tracks: [M, L]`. Ensure the S path
  (discovery-lite → build) has `build.inputs` satisfiable (impl-plan.md now from discovery-lite).
  Add discovery-lite S outputs if the schema records outputs.
- VERIFY: `python core/skills/validate_config.py` and
  `python -m pytest tests/integration/ -q` (lifecycle/state-machine). Confirm an S ticket walks
  discovery-lite → build without a missing-input error.
- COMMIT: `klc-chg3 step-2: phases.yml S path skips acceptance-test-plan`
- Depends-on: step-1.

---

## Change 4 — detailed-test-plan → impl-plan (M); separate phase only for L

Files: `config/phases.yml`, `core/agents/test-planner.md`.

**step-1 — test-planner enriches impl-plan per-step for M**
- Goal: for M, no separate detailed plan — enrich per-step tests in impl-plan (RED/VERIFY already
  added by shipped change A).
- RED: not applicable (prompt edit).
- GREEN: in `test-planner.md` detailed mode, instruct: for M, write the per-step unit/integration
  tests into the existing `impl-plan.md` step fields rather than a separate detailed section; for L,
  keep the standalone detailed-test-plan behaviour.
- VERIFY: manual — test-planner.md branches on track for M vs L.
- COMMIT: `klc-chg4 step-1: detailed tests fold into impl-plan for M`
- Depends-on: change 3 (shares test-planner.md; do after).

**step-2 — phases.yml: detailed-test-plan → [L]**
- Goal: detailed-test-plan is a phase only for L.
- RED: not applicable (config).
- GREEN: set `detailed-test-plan.tracks: [L]`. Verify M path
  (design → build) has impl-plan as build input (already true).
- VERIFY: `validate_config` + `pytest tests/integration/ -q`; an M ticket walks design → build with
  no missing detailed-test-plan gate.
- COMMIT: `klc-chg4 step-2: detailed-test-plan phase L-only`
- Depends-on: step-1, change 3 step-2 (shared phases.yml).

---

## Change 5 — cascade peripheral threshold by lines + size in reason

Files: `core/skills/review_cascade.py`, `config/reviewers.yml`.

**step-1 — add line/hunk thresholds**
- Goal: cap cheap path by diff volume, not just file count.
- RED: extend `tests/integration/test_review_cascade.py` (or add one): an all-peripheral diff of
  few files but > N total lines → `use_full_review == True`.
- GREEN: in `review_cascade.py`, count added+removed lines (and/or per-file) from the diff; compare
  to new config `peripheral_max_lines` / `peripheral_max_lines_per_file`; fall back to full when
  exceeded. Add the keys to `reviewers.yml` with documented defaults (~400–600 total).
- VERIFY: `python -m pytest tests/integration/test_review_cascade.py -q`
- COMMIT: `klc-chg5 step-1: cascade line/hunk threshold`
- Depends-on: none.

**step-2 — diff size in CascadeDecision.reason**
- Goal: the cheap decision string carries size so the manual confirm is informed.
- RED: assert the cheap-path `reason` contains the file and line counts.
- GREEN: format reason as `…→ cheap review (N files, M lines)`.
- VERIFY: pytest the cascade test.
- COMMIT: `klc-chg5 step-2: diff size in cascade reason`
- Depends-on: step-1.

---

## Change 7 — external review default-on for S/M/L (runs always, opt-out only)

Files: `config/reviewers.yml`, `scripts/review.py`, `core/agents/review.md`, `core/phases/doctor.py`.

**step-1 — enable external by default + min_track**
- Goal: external ON for S+; XS never hits the orchestrator anyway.
- RED: not applicable (config).
- GREEN: `reviewers.yml` `external_reviewer.enabled: true`, add `min_track: S`. Document opt-out.
- VERIFY: `validate_config`; grep shows enabled true + min_track.
- COMMIT: `klc-chg7 step-1: external review enabled for S+`
- Depends-on: change 5 (shared reviewers.yml; do after).

**step-2 — opt-out flag + meta field; runs regardless of cheap/full**
- Goal: `--no-external` and `meta.review.skip_external` skip it; otherwise it runs for S/M/L even on
  the cascade cheap path.
- RED: `tests/integration/test_review_external_default.py` — S ticket, no flag → external invoked
  (even when cascade=cheap); `--no-external` → skipped; missing api key → skipped + warn.
- GREEN: add `--no-external` to `review.py` (inverse of `--external`); honour the meta field; invoke
  external for S+ unless opted out or key missing (graceful, existing external-review.md behaviour).
- VERIFY: pytest the new test.
- COMMIT: `klc-chg7 step-2: external opt-out; runs on cheap path too`
- Depends-on: step-1.

**step-3 — review.md wording + doctor warning**
- Goal: prompt reflects default-on; doctor flags missing key.
- RED: not applicable (prompt) for review.md; for doctor add an assertion in its test if one exists.
- GREEN: reword `review.md` step 4 (default-on for S/M/L, list the 3 skip conditions). In
  `doctor.py`, warn when external enabled but `api_key_env` unset.
- VERIFY: manual review.md; `klc doctor` shows the warning with key unset.
- COMMIT: `klc-chg7 step-3: review.md wording + doctor key warning`
- Depends-on: step-2.

---

## Change 6 — learn mandatory for M/L + ADR-accept in retrospective + terse retro

Files: `config/phases.yml`, `core/agents/retrospective.md`.

**step-1 — learn condition includes M/L**
- Goal: learn always runs for M/L; XS/S keep failure-triggers.
- RED: not applicable (config) — guarded by VERIFY.
- GREEN: set learn `condition: "meta.track in ['M','L'] OR meta.rework_count any_overrun OR
  meta.regression_observed == 1 OR meta.budgets any_overrun"`.
- VERIFY: `validate_config` (condition syntax) + `pytest tests/integration/ -q`; a clean M ticket
  reaches learn:work (not skipped).
- COMMIT: `klc-chg6 step-1: learn mandatory for M/L`
- Depends-on: none.

**step-2 — retrospective absorbs ADR-accept**
- Goal: at learn, flip open `Proposed` ADRs to `Accepted`, reconcile consequences vs review-report,
  append lessons_learned.
- RED: not applicable (prompt edit).
- GREEN: in `retrospective.md`, add an ADR-accept section mirroring `adr.md` accept contract (status
  history, `[revised]` consequences, lessons_learned, update CLAUDE.md ADR markers). Only for tickets
  that have a `design/adr.md` in `Proposed`.
- VERIFY: manual — retrospective.md references the adr accept steps and the Proposed→Accepted flip.
- COMMIT: `klc-chg6 step-2: retrospective performs ADR-accept`
- Depends-on: step-1.

**step-3 — terse retro when clean**
- Goal: no boilerplate retro on clean tickets.
- RED: not applicable (prompt edit).
- GREEN: in `retrospective.md`, instruct: if NO failure signal fired, write a short retro (what was
  done, 1 lesson/pattern, estimate accuracy); full template only on rework/regression/overrun.
- VERIFY: manual.
- COMMIT: `klc-chg6 step-3: terse retro when no failure signals`
- Depends-on: step-2.

---

## Change 8 — close the review_depth feedback loop

Files: `core/templates/review-report.md.j2`, `core/agents/retrospective.md`, `core/skills/metrics.py`.

**step-1 — declare fields in the report template**
- Goal: review-report frontmatter formally carries the fields the agent already writes.
- RED: not applicable (template).
- GREEN: add `review_depth`, `full_review_offered`, `full_review_declined` to the frontmatter of
  `review-report.md.j2`.
- VERIFY: render/inspect the template; fields present.
- COMMIT: `klc-chg8 step-1: review-report declares review_depth fields`
- Depends-on: none.

**step-2 — retrospective flags cheap-path misses**
- Goal: retro correlates `review_depth: cheap|lite` with regression/rework.
- RED: not applicable (prompt edit).
- GREEN: in `retrospective.md`, read `review_depth`; if cheap/lite AND regression/rework → emit a
  `cheap-path miss` finding.
- VERIFY: manual — retrospective.md reads review_depth and has the miss rule.
- COMMIT: `klc-chg8 step-2: retro flags cheap-path misses`
- Depends-on: step-1, change 6 step-3 (shared retrospective.md; do after).

**step-3 — rollup cheap-escape-rate per track**
- Goal: aggregate, per track, fraction of cheap/lite reviews that later regressed/reworked.
- RED: add a metrics test — given fixture tickets with review_depth + regression flags, rollup emits
  `cheap_escape_rate` per track.
- GREEN: in `metrics.py` rollup, compute `cheap_escape_rate` into `process-metrics.json`.
- VERIFY: `python -m pytest tests/ -k metrics -q` (or the relevant metrics test).
- COMMIT: `klc-chg8 step-3: rollup cheap-escape-rate per track`
- Depends-on: step-1.

---

## Notes for the implementer

- One logical commit per step; use the COMMIT subject verbatim.
- After config edits to `phases.yml`/`reviewers.yml`/`models.yml`, always run
  `python core/skills/validate_config.py` before committing.
- If a behaviour-changing step's RED test can't be written (no harness for that area), stop and add
  `[!QUESTION blocks=build]` rather than committing untested behaviour.
- Changes touching shared files (phases.yml: 3,4,6 · discovery-lite.md: 1,2,3 · test-planner.md:
  3,4 · reviewers.yml: 5,7 · retrospective.md: 6,8) must follow the global order above to avoid
  rebase churn.
- Change 1 steps marked *(Opus)* are reserved — do not implement those on Sonnet; implement the
  *(Sonnet ok)* sub-steps and the other changes.
