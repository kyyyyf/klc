# Agent prompt — KLC-018 · build:work · step-1

Ticket: **KLC-018** · track: **M** · kind: **bug**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Fix the verified findings from the six `kodex-review.md` files. The
primary defect is that **KLC-013 (discovery-lite + intake routing) was
never merged into main** — restore it and harden its under-spec gaps.
Bundle the remaining confirmed bugs (cascade not wired, telemetry
envelope, scope_delta holes) and one tech follow-up (condition
validation) into the same remediation pass.

## Acceptance Criteria

### [A] KLC-013 restore + harden (PRIMARY)
1. AC-A1: `phases.yml` has `discovery-lite` for `[XS, S]`; `discovery`
   restricted to `[M, L]`. XS/S e2e phase list starts
   `[intake, discovery-lite, ...]`.
2. AC-A2: `route_heuristic.py` present; intake writes `route_hint` +
   `route_signals` to meta.json; intake exposes picks
   `confirm-route` / `force-full-discovery` / `force-xs-skip`.
3. AC-A3: `force-xs-skip` is rejected unless `meta.route_hint == "XS"`
   (guard in intake/ack path — currently absent).
4. AC-A4: `can_complete_discovery_lite` verifies `estimate.total`
   agrees with the XS/S track AND `affected_modules >= 1` (currently
   only checks sections + estimate presence).
5. AC-A5: Ollama fallback resolves an explicit fallback role, not
   `models.resolve("indexing")` ([!FACT src=core/skills/runner.py] the
   013-branch fallback couples to the `indexing` pseudo-phase).

### [B] KLC-015 review cascade wiring (bug)
6. AC-B1: `scripts/review.py` calls `review_cascade.decide()` before
   launching sub-agents ([!FACT src=scripts/review.py:904] sub-agents
   load at `_load_reviewers()`; no cascade call exists). When
   `use_full_review == False`, run a single cheap reviewer.
7. AC-B2: Fail-closed — empty `file_tiers` (classifier failed) OR
   `skipped` scope → `use_full_review = True`
   ([!FACT src=core/skills/review_cascade.py] empty `file_tiers` currently
   falls through to `use_full_review=False`).

### [C] KLC-016 telemetry envelope (bug)
8. AC-C1: Provider envelope is split — only the assistant `result` text
   is written to `out_path`; the `usage` block is parsed separately
   ([!FACT src=core/skills/runner.py:340] `out_path.write_text(stdout)`
   runs before parsing, so JSON mode would corrupt the artifact).
9. AC-C2: After C1, `--output-format json` is enabled by default for the
   anthropic dispatcher so real provider token counts are recorded.
10. AC-C3: OpenAI dispatcher persists its `usage` object too.
    (NOTE: `source=provider` wiring is already correct via KLC-017 —
    do NOT redo it.)

### [D] KLC-012 scope_delta holes (bug)
11. AC-D1: Changed files outside all known module prefixes are surfaced
    (explicit `unknown` bucket) and counted as expansion
    ([!FACT src=core/skills/scope_delta.py:69] `_files_to_modules` silently
    drops unmatched files).
12. AC-D2: For guarded phases (review/integrate), a `skipped` scope
    comparison (no modules.json / no diff) is a hard failure or requires
    an explicit override — not a silent pass
    ([!FACT src=core/phases/ack.py:93] guard only fires when
    `expansion` is non-empty AND `skipped` is absent).

### [E] KLC-014 condition validation (tech)
13. AC-E1: `validate_config.py` flags unrecognised `condition:`
    expressions in `phases.yml` (catch typos at `klc doctor` time).
    Runtime stays fail-open — `_eval_condition` keeps returning True for
    unknown expressions ([!FACT src=core/skills/phases.py:204]); only
    static validation changes.
14. AC-E2: `risk_tags` frontmatter is validated during discovery /
    discovery-lite completion instead of being silently swallowed.

### Current step — step-1

**phases.yml + models.yml (Block A)**

Port intake picks and discovery-lite phase from commit `277f2b7`.


**Changes**:
- `phases.yml` intake: add `pick_required: true`, picks 1=confirm-route
  (goto:next), 2=force-full-discovery (goto:discovery:work),
  3=force-xs-skip (goto:xs-build:work).
- `phases.yml`: add `discovery-lite` phase for `[XS, S]` before
  `discovery`; restrict `discovery` to `[M, L]`.
- `models.yml` phase_roles: add `discovery-lite: coding`.
- `models.yml` per_track.XS: add `discovery-lite: local-simple`.

**Affected files**:

- `config/phases.yml`

- `config/models.yml`


**Expected tests**:

- `python3 -c "import sys; sys.path.insert(0,'core/skills'); import phases as ph; p=ph.load_phases(force=True); print([x.id for x in p.track_phases('XS')])"`



**Rollback**: revert both config files


### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/mnt/d/a_work/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-018 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-018/impl-plan.md`
- Full spec: `.klc/tickets/KLC-018/spec.md`
- Full test-plan: `.klc/tickets/KLC-018/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-018 step-1` and
run `klc step KLC-018 2` to get the next step's card,
or `klc ack KLC-018 --pick 1` if this was the last step.
