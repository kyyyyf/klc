# ADR — KLC-064: throttled feature-ON heartbeat propagation

## Context

`heartbeat_holder` has no production caller, so `steal_holder`'s TTL gate always
measures staleness from `since` and an active holder on a long phase is
wrongly stealable (feature-ON only — single-user never steals). Fixing it means
propagating `heartbeat_at` to the shared `klc-state` branch, which is expensive
(git pull + CAS-push) and, done naively, reintroduces the per-prompt churn
KLC-062 removes and the bare-out-of-`state_tx` write KLC-061 fixes.

## Decision

**D-1 — `heartbeat_at` in the CAS-pushed `meta.holder` is both the peer-visible
liveness and the throttle marker.** A remote peer's `steal_holder` reads liveness
only from `meta.holder` in the pulled `klc-state` subtree, so `heartbeat_at` must
live there. We write it ONLY when we push, so it also records "last pushed" — no
separate marker file.

**D-2 — throttle window = `HEARTBEAT_PUSH_INTERVAL_SECONDS = HOLDER_TTL_SECONDS // 3`.**
Propagate at most once per window per held ticket. `TTL/3` keeps an active
holder's origin `heartbeat_at` within ⅓ TTL of now (3× safety margin below the
steal TTL) while bounding pushes to ≤3 per TTL per ticket.

**D-3 — read-only no-op within the window.** Within the window the command does a
side-effect-free `meta` read and returns 0 with no write/commit/push. This is
what keeps per-prompt UserPromptSubmit calls churn-free (KLC-062).

**D-4 — the write+push goes through the KLC-061 `state_tx` holder envelope.** No
bare write to `meta.holder`. When the window elapses:
`with acquire_lock(ticket): with state_tx(ticket, "heartbeat <K>") as tx: if tx: holder.heartbeat_holder(ticket)`.
`state_tx` does self-heal → pull → body → glob-commit + CAS-push, rolling back the
ticket subtree on any failure. Feature-OFF, `state_tx` yields `None` → the
`if tx:` guard makes it a pure no-op with byte-parity.

**D-5 — feature-OFF is a hard no-op, before any read.** `if not
state_feature.enabled(): return 0` at the top — single-user never steals, so a
heartbeat there is gratuitous churn.

**D-6 — trigger via the UserPromptSubmit hook (throttled).** Reliable during a
long single phase; reuses the `remind` hook shape; best-effort, exit 0.

## Race semantics (steal-vs-heartbeat) — the coherence invariant

Two machines, one ticket. A heartbeats (CAS-push of a fresh `heartbeat_at`); B
attempts a steal (which under KLC-061 also runs inside `state_tx` → pull + CAS
write). CAS-push (non-fast-forward rejection) serializes the two writers on the
`klc-state` branch, so exactly one ordering commits first and the other rebases
onto it:

- If A's heartbeat lands first and is fresh (age < TTL): B pulls it, its
  `steal_holder` sees a fresh `heartbeat_at`, raises `HolderActiveError`, refuses.
  A remains holder. ✔
- If B's steal lands first (A was stale, age ≥ TTL): A pulls it, finds it no
  longer holds the ticket (holder id changed), and its heartbeat is a no-op. B is
  the holder. ✔
- Neither "both win" nor a lost update is possible: the loser of the CAS race
  re-pulls and re-evaluates against the committed state; a heartbeat only ever
  advances the holder it still owns, and a steal only fires against a holder that
  is stale in the pulled state.

The property/fuzz test (AC-5) exercises many interleavings on a real bare-repo
fixture and asserts this invariant, per the KLC-057 real-substrate lesson (stubs
hid the ordering bugs that only a real CAS substrate surfaces).

## Consequences

- Bounded push traffic (≤3/TTL/ticket); zero per-prompt churn; correct feature-ON
  steal-safety; byte-identical feature-OFF.
- Hard merge-order dependency on KLC-061; soft co-constraint with KLC-062.
- Open: the ≤1-per-window prompt pays a synchronous git round-trip (Q-002).
