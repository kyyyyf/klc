# Build log — KLC-064

Wire `heartbeat_holder` (KLC-058), which had no production caller — so
`steal_holder`'s TTL steal-safety was inert. New `klc heartbeat` verb +
UserPromptSubmit hook: feature-ON, it refreshes `heartbeat_at` for held `:work`
tickets and CAS-pushes via KLC-061's `state_tx` holder envelope, THROTTLED to ≤1
push per `HOLDER_TTL_SECONDS // 3`; within the window it is a read-only no-op
(`read_meta_ro`, KLC-062 no-churn). Feature-OFF it is a no-op. Built TDD, branch
`feature/klc-064-wire-heartbeat`, squash-merged to main as `8414526` (PR #68).

Design note: the FIRST design (S, feature-OFF, write-every-prompt) was sent back
at design-pass and re-scoped S→M — a heartbeat's value is entirely multi-user, and
it must not reintroduce the per-prompt churn KLC-062 removes. The accepted shape
(`design/adr.md`): `heartbeat_at` in the CAS-pushed `meta.holder` is both the
peer-visible liveness AND the throttle "last-pushed" marker (no separate marker
file); window = `TTL/3`; read-only no-op within the window; write+push through the
KLC-061 envelope.

Note on TDD evidence: the feature branch was squash-merged, so per-step RED→GREEN
commits are collapsed into `8414526` on main. RED test names and the RED→GREEN
order are recorded per step and in `## Evidence`; completed steps are marked `[x]`
in `impl-plan.md`.

## step-1 [x] — throttle constant + `klc heartbeat` verb (feature-ON write via state_tx)
**RED:** `tests/integration/test_heartbeat.py::test_feature_on_first_push_advances_heartbeat_at_at_origin` and `::test_long_hold_active_holder_not_stealable` — fail (no command, no propagation; an active holder on a long phase is wrongly stealable).
**GREEN:** add `HEARTBEAT_PUSH_INTERVAL_SECONDS = HOLDER_TTL_SECONDS // 3`; `klc heartbeat` refreshes `heartbeat_at` for held `:work` tickets and CAS-pushes via the KLC-061 `state_tx` holder envelope.
**Outcome:** green

## step-2 [x] — non-blocking UserPromptSubmit hook
**RED:** `tests/integration/test_heartbeat.py::test_hook_exits_0_on_child_failure` and `::test_within_window_is_readonly_noop` — fail (no hook; churn on repeat).
**GREEN:** add a best-effort UserPromptSubmit hook that dispatches `klc heartbeat`; within the throttle window it does a side-effect-free `read_meta_ro` and returns 0 (no write/commit/push).
**Outcome:** green

## step-3 [x] — feature-OFF parity + best-effort hardening + docstring truth-up
**RED:** `tests/integration/test_heartbeat.py::test_feature_off_meta_byte_identical` and `::test_advisory_never_crashes_exits_0` — fail until the feature-OFF hard guard and error-swallowing are in place.
**GREEN:** feature-OFF is a hard no-op (byte-identical meta); the advisory never crashes (exit 0 on any error).
**Outcome:** green

## step-4 [x] — steal-vs-heartbeat property/fuzz test on a REAL bare-repo substrate
**RED:** `tests/integration/test_heartbeat_race.py::test_steal_vs_heartbeat_coherence_over_interleavings` — fails until steps 1-3 land and compose with KLC-061's `state_tx`-wrapped `steal`.
**GREEN:** two-worktree CAS race on a real bare repo — both interleavings produce a legal winner; the full coherence invariant holds; stable at 40 rounds.
**Outcome:** green

## Evidence

```
$ python3 -m pytest tests/integration/test_heartbeat.py -q
15 passed
```

```
$ python3 -m pytest tests/integration/test_heartbeat_race.py -q
# real bare-repo two-worktree CAS race; both winners; full coherence invariant; stable at 40 rounds
passed
```

```
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
812 passed
```

Feature-OFF byte-parity: with the state feature off, `klc heartbeat` and the hook
are hard no-ops — `meta.json` is byte-identical.

## Review-fix round — 2026-07-16 (fresh general-purpose + `codex exec review --base main`)

The fresh reviewer found NO HIGH/MEDIUM — the concurrency design was confirmed
sound (throttle marker reflects origin; race guard doubly-safe = pull
StaleStateError + in-body ownership recheck; CAS one-winner). codex found one P2;
two LOWs from fresh. All fixed TDD. Full assessment in `review-report.md`.

- P2 codex: the scan aborted entirely if one ticket's `acquire_lock` raised, so
  later held tickets went unrefreshed → per-ticket `try/except: continue`.
  RED→GREEN.
- LOW fresh ×2: a misleading docstring (the load-bearing `except` catches
  `StaleStateError`, not `NothingToCommitError`) reworded; `os.getcwd()` moved
  inside the `try` so a deleted cwd still exits 0.

```
$ python3 -m pytest tests/integration/test_heartbeat.py -q
# per-ticket try/except: continue — later held tickets still refreshed when one raises
15 passed
```

```
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
812 passed
```
