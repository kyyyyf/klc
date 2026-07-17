---
ticket: KLC-064
authority: hybrid
last_generated: 2026-07-16T00:00:00Z
---

# Test plan — KLC-064 (throttled feature-ON heartbeat)

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/integration/test_heartbeat.py::test_feature_on_first_push_advances_heartbeat_at_at_origin | Real bare-repo klc-state fixture; identity holds K in `:work`; window elapsed (old `since`); `klc heartbeat` writes `heartbeat_at` and a peer pull observes the advanced value. |
| AC-2 | acceptance | tests/integration/test_heartbeat.py::test_within_window_is_readonly_noop | After a push, an immediate second `klc heartbeat` performs NO write/commit/push; klc-state tree hash byte-identical; git status clean. |
| AC-2 | acceptance | tests/integration/test_heartbeat.py::test_at_most_one_push_per_window | Drive many calls inside one window → exactly one CAS-push (assert commit count on klc-state). |
| AC-3 | acceptance | tests/integration/test_heartbeat.py::test_long_hold_active_holder_not_stealable | Simulate a long hold (old `since`); heartbeat advances `heartbeat_at`; peer `steal_holder` (default TTL) raises `HolderActiveError`; after a full TTL of heartbeat silence the peer steal succeeds. |
| AC-4 | acceptance | tests/integration/test_heartbeat.py::test_feature_off_meta_byte_identical | Feature OFF: `klc heartbeat` leaves `meta.json` byte-for-byte identical; no git invoked. |
| AC-4 | acceptance | tests/integration/test_heartbeat.py::test_advisory_never_crashes_exits_0 | Missing identity, corrupt/unreadable meta, absent holder, and a stubbed pull/push failure each leave exit 0, no traceback. |
| AC-4 | acceptance | tests/integration/test_heartbeat.py::test_hook_exits_0_on_child_failure | `klc-plugin/hooks/heartbeat.py` returns 0 even when the child errors; no stdout forwarded (silent). |
| AC-5 | property/fuzz | tests/integration/test_heartbeat_race.py::test_steal_vs_heartbeat_coherence_over_interleavings | REAL bare-repo klc-state fixture, two worktrees (A=holder heartbeat, B=stealer). Randomized/enumerated interleavings; invariant holds every time (see below). No stubs for the CAS layer. |
| AC-6 | regression | tests/test_holder.py, tests/test_holder_steal.py, tests/integration/test_remind.py | Existing holder/steal/remind suites stay green. |

## Race invariant (AC-5) asserted for every interleaving
- Exactly one of {A stays holder with a fresh `heartbeat_at`} or {B is the new
  holder} is true at the end — never both, never neither.
- No lost update: the final `klc-state` commit chain is linear (CAS serialized);
  the CAS loser rebased and re-evaluated.
- If B stole, A's subsequent heartbeat is a no-op (A no longer holds K).
- If A's fresh heartbeat won the race, B's steal was refused with
  `HolderActiveError` (never a fresh-but-stolen holder).
- No stale-but-unstealable state: after a full TTL of silence, B always succeeds.

## Edge cases
- Window boundary: `age(heartbeat_at) == HOLDER_TTL_SECONDS // 3` exactly →
  propagate (>= window). Just under → no-op.
- Holder has only `since` (no prior `heartbeat_at`): throttle measures from
  `since`; first propagation adds `heartbeat_at`.
- CAS-push rejected/rolled back: `heartbeat_at` reverts to the pre-tx value; the
  next call (window still elapsed) retries; never a partial write.
- Multiple identity-held `:work` tickets: each throttled independently; one
  failing must not abort the others.
- Ticket held by ANOTHER identity: never heartbeated (must not refresh a peer).
- Corrupt (non-dict) holder / non-string phase: skipped robustly, exit 0.
- `heartbeat_at` write must never make a genuinely-stale holder un-stealable
  (fallback to `since` in `_holder_age_seconds` preserved).

## Regression scenarios
- `core/phases/steal.py` (post-KLC-061): TTL gate still refuses fresh / permits
  stale; steal now runs inside `state_tx` — heartbeat must compose with it.
- `core/skills/holder.py`: `heartbeat_holder` preserves siblings; raises on absent
  holder; `HEARTBEAT_PUSH_INTERVAL_SECONDS < HOLDER_TTL_SECONDS`.
- `core/phases/remind.py` (post-KLC-062): shared UserPromptSubmit hook chain still
  emits reminders and stays read-only; adding the heartbeat hook must not perturb
  remind output or reintroduce per-prompt churn.
- `scripts/klc`: `heartbeat` dispatches as lifecycle and is in `NO_DRAIN_CMDS`.
- Feature-OFF: all existing intake/ack/next/holder tests byte-identical.

## Manual checklist (populated iff estimate.manual >= 2)
- estimate.manual = 1: single manual sanity — two real clones of the project on
  the `klc-state` branch; hold a ticket on machine A, let it heartbeat, confirm
  `klc steal` on machine B is refused while A is active and succeeds after A goes
  silent for a full TTL.

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
