# Intake (phase reference)

> **Human context**: See [docs/phases/intake.md](../../docs/phases/intake.md) for intake phase overview and ack options.

## How intake works (no LLM by default)

`klc intake` is **deterministic** — it runs no LLM in the hot path. It:

1. Writes `raw.md` + `meta.json`, appends to the global ticket index.
2. Classifies a **provisional** track via `core/skills/route_heuristic.py`
   (signals: kind, length, EN/RU keywords, module mentions; max-wins,
   downgrades forbidden) and records `route_hint`, `route_confidence`,
   `route_signals`, `route_decision`, and `mentions` in `meta.json`.
3. Lands on `intake:ack-needed` and prints a confidence-aware recommendation.

The track here is a **provisional floor, not the final track** — Discovery
(or Discovery-lite) is the authoritative classifier.

## Routing recommendation (B+A)

`route_decision` (from `route_heuristic.decide_route`) drives the printed
guidance:

- **trust** (high confidence, or hint already ≥ M) → confirm route:
  `klc ack <KEY> --pick 1`.
- **triage** (short, low/medium confidence, hint ≤ S) → run the cheap
  **intake triage** (`core/agents/intake-triage.md`) to check for hidden
  scope before committing to a small track; or `--pick 2` to force full
  discovery.
- **full-discovery** (low confidence, triage disabled via
  `KLC_INTAKE_TRIAGE=0`) → `klc ack <KEY> --pick 2` (force-full-discovery).

Why: a short description usually means *under-specified*, not *simple*
(e.g. "support light theme" is short but cross-cutting). Length raises
confidence when long; it never lowers the track.

## Enrichment notes

When the triage agent runs and finds the description too vague, it appends
the missing facts (never invented answers) to `raw.md`:

```
<!-- BEGIN: intake-notes -->
- provisional_track: M (was S) — reason: cross-cutting UI change
- missing: which components? dark theme too?
<!-- END: intake-notes -->
```

Discovery and the XS fast-track read this block.

## What intake never does

- Does not run a full estimate (4 axes) — that is Discovery.
- Does not write `spec.md`.
- Does not pick the final track — only a provisional `route_hint`.

## Completion signal

`klc intake` prints, on success:

```
INTAKE_OK <ticket-key>
```

## Completion signal (orchestrator)

In addition to any phase-specific signal above, end your final output
with exactly one fenced JSON object, as the LAST block in your response:

```json
{"phase":"<phase-id>","signal":"done","artifacts":["path/relative/to/ticket/dir.md"],"blocking_questions":[],"next_action":"ack"}
```

- `phase` — the phase id you were dispatched for (your agent name after
  the `klc-` prefix, e.g. `klc-design` -> `"design"`).
- `signal` — `"done"` | `"blocked"` | `"failed"`.
- `artifacts` — paths you wrote, relative to the ticket directory.
- `blocking_questions` — string[]; leave `[]` if none. Blank/empty
  entries are ignored by the orchestrator.
- `next_action` — `"ack"` | `"clarify"` | `"stop"`.
- Optional: `"tokens":{"in":N,"out":N}`.

This is consumed by the `/klc:run` orchestrator (KLC-052) to decide the
next step without re-reading your artifacts. It does not replace any
phase-specific signal line above — both are expected.
