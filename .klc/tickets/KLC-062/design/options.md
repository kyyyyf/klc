# KLC-062 — Approaches (discovery shortlist detail)

Problem: `klc remind` (and, on the legacy-phase path, `klc status`) writes
`meta.json` while claiming to be read-only. Two write sites: (1) the
`_sync_risk_tags` / floor-guard writes inside `can_complete_discovery[_lite]`
reached from the completion probe, and (2) `read_meta`'s persist-on-migrate.

## Approach A — side-effect-optional completion probe + non-persisting read (PICKED)

Thread a defaulted `persist: bool = True` keyword through `can_complete`,
`can_complete_discovery`, and `can_complete_discovery_lite`, guarding the two
write sites (`_sync_risk_tags(ticket)` at `phase_completion.py:172,360` and the
floor-guard `_lc.write_meta` at `:157`). Read-only callers (`remind`, and the
`gate_policy` advisory probe) pass `persist=False`; `ack.py:82` keeps the default
so it still persists at the real transition. For the legacy-migration write-back,
give `lifecycle.read_meta` a defaulted `persist_migration: bool = True` and add a
thin `read_meta_ro(ticket)` wrapper; `status._meta` and `remind._scan` use the
read-only variant (in-memory migration still happens for correct display, only the
write is suppressed).

- Pros:
  - Fixes the root cause on EVERY read-only caller, not just `remind` (also
    silences the latent `gate_policy` write).
  - Backward-compatible: defaulted keywords mean `ack` and all other callers keep
    today's behaviour verbatim → smallest blast radius on a foundational API
    (satisfies C-002/C-003).
  - `risk_tags` and floor-guard audit still persist exactly at the `ack` path
    (AC-3, no functional regression).
  - Symmetric with `board.py`'s existing raw-read discipline (AC-2).
- Cons:
  - Adds a keyword to a hot API; every write site must be correctly gated or the
    fix is incomplete (mitigated by AC-4 byte-identical tests on the discovery and
    legacy paths).
  - Persistence logic still lives inside `can_complete` rather than at the caller.

## Approach B — relocate persistence to the ack path

Make the whole `can_complete` family strictly read-only (delete the two write
sites) and move `_sync_risk_tags` plus the floor-guard `track_source`/`blast_radius`
persistence into `ack.py` after a successful `can_complete`.

- Pros:
  - Cleanest separation of concerns: probes never write; only `ack` mutates.
  - Removes the write from every probe caller in one move.
- Cons:
  - Higher risk on a foundational path: the floor-guard write is entangled with the
    downgrade-safety computation (`is_downgrade_safe`, `modules.json` read) — moving
    it means `ack` must re-run or receive that computed audit, widening the change.
  - More surface area to regress `risk_tags`/audit behaviour for real transitions
    (AC-3 risk).

## Approach C — special-case discovery inside remind

In `remind`, detect `discovery`/`discovery-lite` and either skip the writing checker
or substitute a hand-rolled read-only completeness check.

- Pros:
  - Smallest diff, confined to `remind.py`.
- Cons:
  - Narrow: does not fix `status`'s legacy-migration write, the `gate_policy`
    latent write, or `discovery-lite` unless special-cased too.
  - Duplicates gate logic in `remind`, which drifts from `phase_completion` over time.
  - Treats the symptom (one caller) rather than the read-only contract itself.

## Decision

Picked A. It is the root-cause fix with the least blast radius given the backward-
compatible defaulted keywords, keeps persistence at the correct `ack` transition,
and generalises to the `status`/legacy path and the `gate_policy` probe.
