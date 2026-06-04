---
ticket: KLC-018
kind: bug
authority: human
last_generated: 2026-06-04
risk_tags: [data]
---

# KLC-018 — Kodex-review remediation (KLC-011..016 findings)

## Goals

Fix the verified findings from the six `kodex-review.md` files. The
primary defect is that **KLC-013 (discovery-lite + intake routing) was
never merged into main** — restore it and harden its under-spec gaps.
Bundle the remaining confirmed bugs (cascade not wired, telemetry
envelope, scope_delta holes) and one tech follow-up (condition
validation) into the same remediation pass.

## Problem / Context

Six review files in `.klc/tickets/KLC-01{1..6}/kodex-review.md` were
written by an external reviewer. Each finding was re-verified against
the **current** code (branch `feature/KLC-017-token-sweep`, which mirrors
`gl/main` + the open KLC-017 commit). Verdicts:

- **KLC-011** — clean, no action (review said Approve; confirmed).
- **KLC-013** — NOT delivered. Highest-impact finding.
- **KLC-015** — cascade module exists but is dead code.
- **KLC-016** — two real bugs remain; one finding already fixed by KLC-017.
- **KLC-012** — two real scope-guard holes.
- **KLC-014** — one tech hardening (fail-open is intentional; validation gap is real).

### KLC-013 absence — evidence
[!FACT src=config/phases.yml] main's `phases.yml` has `discovery` with
`tracks: [XS, S, M, L]` and no `discovery-lite` phase, no intake route picks.
[!FACT src=core/skills] `route_heuristic.py` is absent from main.
[!FACT] No `KLC-013` commit in `gl/main` history (`git log --grep`).
[!FACT src=core/agents/discovery-lite.md] The agent file exists in main
but only because KLC-014 (`ed0e10d`) added it as an orphan — nothing in
`phases.yml` references it.
[!FACT src=feature/KLC-013-discovery-lite] The full implementation lives
in commit `277f2b7`: `route_heuristic.py`, `discovery-lite` phase for
`[XS,S]`, intake picks `confirm-route`/`force-full-discovery`/`force-xs-skip`.

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

## Non-goals

- Re-doing KLC-016 `source=provider` wiring (KLC-017 already fixed it).
- Moving the integrate guard earlier than ack: in current `phases.yml`
  `integrate:work` is a no-agent checklist with no irreversible work
  (merge is performed by a human), so the late-guard finding is
  documented, not implemented.
- Changing `_eval_condition` runtime behaviour (fail-open is intended).
- KLC-011 (verified clean).

## Affected modules

- `config/phases.yml` — discovery-lite phase, intake picks — [A]
- `core/skills/route_heuristic.py` (port from 013 branch) — [A]
- `core/phases/intake.py` — route_hint/signals, force-xs-skip guard — [A]
- `core/skills/phase_completion.py` — discovery-lite checks, risk_tags — [A][E]
- `core/skills/runner.py` — Ollama fallback role, envelope split, json mode — [A][C]
- `config/models.yml` — discovery-lite role, per_track — [A]
- `scripts/review.py` — cascade wiring — [B]
- `core/skills/review_cascade.py` — fail-closed — [B]
- `core/skills/scope_delta.py` — unknown bucket — [D]
- `core/phases/ack.py` — skipped=hard-fail — [D]
- `core/skills/validate_config.py` — condition syntax check — [E]
- `tests/` + `docs/process.md`

## Open questions

None blocking. Merge strategy for [A]: cherry-pick/port `277f2b7` onto
current main and resolve conflicts in `phases.yml`, `models.yml`,
`phase_completion.py` (touched by 014/016), rather than a raw branch merge.

## Estimate

- complexity: 3 (5 distinct areas, cross-cutting, merge-conflict resolution)
- uncertainty: 2 (013 rebase conflicts; review.py wiring surface unknown)
- risk: 2 (scope guard + telemetry touch quality gates and artifact writes)
- manual: 1 (verify real review.py cascade run)
- total: 8 → **M-track**
