# KLC-060 — Approach options

Scope recap: `klc board` and `klc status` surface the current-phase `holder`
and a "waiting on ack from `<id>`" hint, derived read-only from `meta.json`.
The `holder: {id, machine, since}` field is introduced by KLC-056 (not yet
built); KLC-060 must tolerate its absence.

Both commands already have the parsed `meta` dict in hand:
- `board.py` projects `{key, track, kind}` per ticket (core/phases/board.py:33-37).
- `status.py` annotates the current phase in `_annotate_current` and already
  branches on the `ack-needed` state (core/phases/status.py:129-146).

So the work is "format a holder string from meta and inject it at the existing
render points." The only real choice is *where the formatting logic lives*.

---

## Option A — Inline projection in each command

Read `holder` directly inside `board.py` and `status.py` at the points where
`meta` is already available, and format the string in place.

Pros
- Smallest diff; no new file.
- No new import wiring.

Cons
- The "holder label" and "waiting on ack from <id>" wording is duplicated in
  two places and will drift (board says "held by", status says "waiting on
  ack from" — easy to let them diverge on null handling).
- The coupling to KLC-056's field shape (`holder.id`) is repeated, so a
  field-name change touches two files instead of one.
- Two copies of the null/missing-holder guard to test.

## Option B — Shared `holder_display` helper in a skill (PICKED)

Add a tiny helper module under `core/skills` (e.g. `holder_display.py`) with
two pure functions:
- `holder_label(meta) -> str | None` — returns the holder id (or a short
  "held by <id>" label), or `None` when no holder is present.
- `waiting_hint(meta, state) -> str | None` — returns `"waiting on ack from
  <id>"` only when `state == "ack-needed"` and a holder id is present.

`board.py` and `status.py` import it and inject the returned strings at their
existing render points; both treat `None` as "render as today."

Pros
- Single source of truth for wording and for the KLC-056 field-shape coupling
  (C-002): one place to adjust if the field name changes.
- Pure functions over a dict → trivially unit-testable, no I/O; covers the
  manual axis (no board/status unit tests exist today, src=tests/ has no
  board/status file).
- Guards the missing-holder / null case once, used by both surfaces.

Cons
- One extra small file and two import lines vs. Option A.

Decision: **Option B.** The deciding factor is C-002 (absence must be tolerated
identically on both surfaces) plus the shared wording requirement — both argue
for one tested formatter rather than two inline copies. The extra file is
negligible for an XS ticket and pays for itself the moment KLC-056 finalises the
field shape.

---

## Dependency note

KLC-056 introduces the `holder` field. KLC-060's display reads it but does not
require it to exist at runtime (absence renders as today). Implementation can
land before or after KLC-056; if it lands first, the new columns simply stay
empty until holders are written.

## Dependency impact

`dependency-impact: unavailable (no .klc/index/depgraph.json; modules.json
carries no reverse edges)`. Fell back to direct call-site inspection of the two
touched files plus a word-boundary grep for existing references.

- **Downstream** (what the touched files import): `board.py` → `_paths`;
  `status.py` → `_paths`, `lifecycle`, `phases`. None change.
- **Upstream (dependents)**: `board.py` and `status.py` are CLI entry points
  dispatched by `scripts/klc`; nothing imports them as libraries (grep for
  `import board` / `import status` under `core/` and `tests/` is empty), so the
  change is additive to output only and does not break a dependent.
- **Edges added by the picked option (B)**: two *new, same-direction* edges —
  `core/phases/board.py → core/skills/holder_display` and
  `core/phases/status.py → core/skills/holder_display`. This is the existing
  `phases → skills` import direction (both files already import `_paths`,
  `phases`, `lifecycle` from skills). No edge is inverted; skills do not import
  phases, so no cycle is created.
- **Scope**: both new edges stay inside the single declared affected module
  `core/phases`; no dependent outside `affected_modules` is touched, so no
  scope-expansion question is raised.

Risk note carried into the plan: the new `holder.id` read is the only coupling
to the not-yet-built KLC-056 field shape; D-003 confines it to one helper that
returns `None` on every degraded shape, so absence renders as today (C-002).

ADR_NEEDED=no

Rationale: the new edges are additive and same-direction (no boundary crossed,
no edge inverted, no cycle), there is no external dependency, no data-schema or
persistence change, no change to an existing public-API signature (only a new
private helper), and no layer crossing (code↔code). The cleaner option (B) was
*chosen*, not rejected, so the "cleaner option rejected for pragmatic reasons"
trigger does not fire either.
