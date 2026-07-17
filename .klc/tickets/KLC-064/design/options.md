# Design options — KLC-064 (heartbeat wiring, feature-ON throttled)

Two orthogonal decisions: (A) how propagation is throttled + where the
"last-pushed" marker lives, and (B) what triggers the heartbeat.

## Decision A — throttle mechanism & marker location

- **Option A1 — `heartbeat_at` IS the marker; throttle both write and push
  together (PICKED).** On each call: read `meta.holder` (side-effect-free); if
  `age(heartbeat_at else since) < HOLDER_TTL_SECONDS/3` → pure no-op (no write,
  no commit, no push). Only when the window has elapsed do we write
  `heartbeat_at` and CAS-push it inside `state_tx`. Because we write
  `heartbeat_at` ONLY when we push, the value already in the CAS-pushed
  `meta.holder` IS the "last-pushed" timestamp — no separate marker.
  - Pros: zero extra state; the throttle marker and the peer-visible liveness are
    the same field, so they can never drift; zero per-prompt tracked-tree write
    (KLC-062 no-churn); self-correcting (a failed/rolled-back push leaves the old
    `heartbeat_at`, so the next call retries).
  - Cons: no "local-often" freshness — but that has no consumer (see below).

- **Option A2 — local-often touch + separate last-pushed marker.** Update a
  local, git-ignored `heartbeat_at` sidecar on every prompt; keep a separate
  last-pushed timestamp; copy to the tracked `meta.holder` + CAS-push only when
  the window elapses.
  - Pros: a locally-fresh liveness value for local tooling.
  - Cons: extra state that can drift from what peers actually see; the
    "local-often" value has **no consumer** — the local machine is the holder and
    never steals from itself, and the only reader whose decision matters is a
    REMOTE peer's `steal_holder`, which reads `meta.json` from the pulled
    `klc-state` branch. More moving parts for no behavioural gain.

- **Option A3 — put `heartbeat_at` in a lighter, non-CAS channel** (e.g. a git
  note, a side ref, or a non-tracked file).
  - Cons: **rejected on correctness.** A remote peer's `steal_holder` reads
    liveness from `meta.holder` in the pulled `klc-state` subtree. A channel that
    is not part of that CAS-pushed subtree is invisible to the peer's steal gate,
    so it cannot protect an active holder — defeating the whole ticket.

**Picked: A1.** `heartbeat_at` lives in the CAS-pushed `meta.holder` (the only
place a peer's steal reads) and doubles as the last-pushed throttle marker.

## Decision B — trigger

- **Option B1 — UserPromptSubmit hook calling `klc heartbeat` (PICKED).** Mirrors
  the `remind` hook. Fires on every agent turn (the real "agent loop" cadence),
  but the command is throttled so all but ~1-per-window calls are read-only
  no-ops.
  - Pros: reliably fires during a long single phase (the build case) where there
    are NO `ack`/`next` transitions; reuses the proven non-blocking best-effort
    hook shape; per-prompt cost is a cheap read.
  - Cons: the ≤1-per-window prompt that actually pushes pays a synchronous git
    round-trip inside the hook timeout (~1-2 s). Tracked as spec Q-002.

- **Option B2 — heartbeat only on `ack`/`next` transitions.** Fold into the
  already-`state_tx`-wrapped verbs.
  - Cons: a long single phase has no intervening transitions, so `heartbeat_at`
    never advances during the very phase that outlives the TTL. Insufficient
    alone. (Also redundant: entering a new phase already re-acquires the holder
    with a fresh `since`.)

- **Option B3 — background daemon thread.** Rejected: threading complexity,
  abrupt-exit caveats, no fit with the synchronous-over-files design.

**Picked: B1** (hook + throttle), with the latency trade-off flagged as Q-002 for
the operator. The `klc heartbeat` verb it introduces is also directly callable, so
a build loop can invoke it explicitly if ever needed.

## Rejected earlier scoping (why this is no longer S)

The original S plan wrote `heartbeat_at` to `meta.json` on EVERY UserPromptSubmit
and targeted feature-OFF. That (1) delivered zero value (no steal in single-user),
(2) reintroduced the exact per-prompt churn KLC-062 removes, and (3) wrote bare
outside `state_tx` (the KLC-061 P1). The correct design is feature-ON-first,
throttled, and built on the 061 envelope — concurrency/coordination work → M.
