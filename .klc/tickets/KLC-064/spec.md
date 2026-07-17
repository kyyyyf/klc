---
ticket: KLC-064
kind: feature
authority: hybrid
track: M
last_generated: 2026-07-16T00:00:00Z
risk_tags: [data]
depends_on: [KLC-061]
constrained_by: [KLC-062]
---

# KLC-064 — Wire heartbeat_holder as a real, throttled, feature-ON writer

## Goals

- Give `heartbeat_holder` a **real production caller** so that under multi-user
  (feature-ON) mode an actively-held ticket's `heartbeat_at` advances at origin
  and a legitimately-active holder cannot be stolen while still working.
- Make the propagation to origin **throttled**: `heartbeat_at` reaches the
  `klc-state` branch via a `state_tx` CAS-push **at most once per ~⅓ of
  HOLDER_TTL_SECONDS**, so an active holder stays protected without a git
  pull+CAS-push on every prompt.
- Introduce **zero per-prompt tracked-tree churn**: within the throttle window
  the heartbeat is a pure read-only no-op (no meta write, no commit, no push) —
  it must not reintroduce the per-UserPromptSubmit `meta.json` dirtiness that
  KLC-062 removes.
- Keep **feature-OFF byte-parity**: in single-user mode nobody steals, so
  heartbeat is a pure no-op and `meta.json` is byte-for-byte unchanged.

## Problem / Context

`heartbeat_holder` (KLC-058, `core/skills/holder.py:162`) and its consumer, the
`steal_holder` TTL gate (`core/skills/holder.py:222`, `core/phases/steal.py`),
both assume "a live agent keeps it fresh with `heartbeat_holder`". A repo-wide
grep finds **zero production callers** — no agent prompt, command, phase, or hook
writes `heartbeat_at`. Consequence: `_holder_age_seconds` always falls back to
`since` (acquire time), so a holder on a phase running longer than
`HOLDER_TTL_SECONDS` (e.g. a long build) becomes stealable while still working —
exactly the case the `heartbeat_at`-preference logic was built to prevent. The
primitive is correct; this is a wiring gap.

Three facts reshape the fix from "S wiring" into an M coordination change:

1. **The value is entirely feature-ON.** `steal` is a multi-user verb; in
   single-user (feature-OFF) mode nobody steals, so a feature-OFF-only heartbeat
   solves a non-problem. The primary target is feature-ON.
   FACT: `state_feature.enabled()` is the single ON/OFF switch; feature-OFF makes
   `state_tx` a pure pass-through no-op. src=core/skills/state_feature.py:39,
   core/skills/state_tx.py verified=2026-07-16.

2. **Naive wiring conflicts with KLC-062.** KLC-062 makes `klc remind` truly
   read-only because `can_complete`/`_sync_risk_tags` rewrote `meta.json` on
   EVERY UserPromptSubmit (per-prompt git-dirty churn). A heartbeat that writes
   `heartbeat_at` on every prompt reintroduces exactly that churn. The propagation
   must therefore be throttled, and the no-op path must use a side-effect-free
   meta read (KLC-062 also fixes that `lifecycle.read_meta` performs legacy-phase
   migration writes). src=.klc/tickets/KLC-062/raw.md verified=2026-07-16.

3. **Feature-ON correctness depends on KLC-061's envelope.** Under feature-ON a
   bare write to `meta.holder` OUTSIDE `state_tx` dirties the tracked `.klc`
   worktree and never reaches origin — the P1 KLC-061 fixes for `steal`. But
   naively wrapping heartbeat in `state_tx` = a git pull+CAS-push on every prompt
   per held ticket, far too heavy. The throttle reconciles the two.
   FACT: `state_tx` is the ONLY component that touches git when the feature is ON;
   it does self-heal → pull → body → glob-commit + CAS-push once, and rolls back
   the ticket subtree on any failure. src=core/skills/state_tx.py:1-40
   verified=2026-07-16.

## Dependencies (merge-order)

> [!DEPENDENCY D-061] hard, merge-order source=operator-brief
> Builds ON **KLC-061** (`feature/klc-061-wrap-verbs-state-tx`), which wraps the
> holder-mutating verbs (incl. `steal`) in `state_tx`, fixing the bare
> out-of-`state_tx` holder-write P1. **KLC-061 merges first.** Heartbeat's write
> reuses the exact `state_tx` holder-mutation envelope 061 establishes for
> `steal` — it does NOT write bare and does NOT re-implement the envelope.
> Without 061 merged, heartbeat would either (a) reintroduce the P1 (bare write
> that never propagates) or (b) collide with 061's edits in `steal.py`/`holder.py`.

> [!DEPENDENCY D-062] soft co-constraint source=operator-brief
> Aligns with **KLC-062** (`feature/klc-062-remind-read-only`): the heartbeat
> no-op path (within the throttle window) must use KLC-062's side-effect-free
> meta read so repeated UserPromptSubmit calls leave the `klc-state` tree
> byte-identical. Heartbeat must NOT reintroduce per-prompt churn.

## Acceptance Criteria

1. **AC-1 (feature-ON real writer, via the 061 envelope):** When the feature is
   ON and the current identity holds ticket `K` in a `<phase>:work` state,
   `klc heartbeat` (driven by the UserPromptSubmit hook) writes
   `meta.holder.heartbeat_at` and propagates it to origin on the `klc-state`
   branch through a `state_tx` CAS-push — reusing the holder-mutation envelope
   KLC-061 establishes, never a bare out-of-`state_tx` write. A peer that pulls
   then observes an advanced `heartbeat_at`.

2. **AC-2 (throttled propagation, no per-prompt churn):** `klc heartbeat`
   propagates (writes + CAS-pushes) **at most once per
   `HEARTBEAT_PUSH_INTERVAL_SECONDS` (= `HOLDER_TTL_SECONDS // 3`, i.e. 10 min at
   the default TTL) per held ticket**. When the current `heartbeat_at` (else
   `since`) is younger than that window, the command is a pure read-only no-op:
   no tracked-tree write, no commit, no push. Repeated UserPromptSubmit
   invocations therefore leave the `klc-state` tree byte-identical (KLC-062
   no-churn). The throttle probe uses a side-effect-free meta read.

3. **AC-3 (steal-safety made real):** Under feature-ON, a ticket actively worked
   longer than `HOLDER_TTL_SECONDS` is NOT stealable by a peer — throttled
   heartbeats keep origin `heartbeat_at` within `HOLDER_TTL_SECONDS/3` of now
   while the agent is active, so a peer's `steal_holder` measures staleness from
   the fresh `heartbeat_at` (not `since`) and raises `HolderActiveError`. Once
   heartbeats stop for a full `HOLDER_TTL_SECONDS` of silence, the peer's steal
   succeeds. This gives the KLC-058 `heartbeat_at`/`since` fallback a real writer.

4. **AC-4 (feature-OFF parity + best-effort):** When the feature is OFF,
   `klc heartbeat` is a pure no-op — no `meta.json` write, byte-for-byte
   identical state, no git — because no peer can steal in single-user mode. In
   BOTH modes the command and its hook are best-effort: they always exit 0, do no
   blocking work on the throttled no-op path, and swallow every error (missing
   identity, unreadable/corrupt meta, absent holder, pull/push failure) so they
   never crash or block the surrounding prompt/phase.

5. **AC-5 (steal-vs-heartbeat race — real substrate):** A property/fuzz test on a
   **real bare-repo `klc-state` fixture** (two worktrees = two machines), not
   stubs, interleaves a heartbeat CAS-push on machine A with a `steal` attempt on
   machine B across many orderings and asserts the coherence invariant: for every
   interleaving the final holder is consistent — either B is refused and A stays
   holder with a fresh `heartbeat_at`, or B steals and A's next heartbeat is a
   no-op (A no longer holds) — never a lost update, never both-win, never a
   fresh-but-stolen or stale-but-unstealable holder. CAS-push (non-fast-forward
   rejection) serializes the two writers. (Mirrors the KLC-057 real-substrate
   lesson.)

6. **AC-6 (tests):** Integration + property tests cover: throttle no-op within
   window and single push per window (AC-2), steal-safety over a simulated long
   hold (AC-3), feature-OFF byte-parity and best-effort-never-crashes (AC-4), the
   AC-5 race property test, and regression that existing
   `tests/test_holder.py`, `tests/test_holder_steal.py`, and
   `tests/integration/test_remind.py` stay green.

## Non-goals

- Re-implementing `heartbeat_holder`/`steal_holder`/`state_tx` — this ticket
  supplies the caller and the throttle, not the primitives.
- Wrapping `steal`/`ship`/`abort`/`jump`/`jira` in `state_tx` — that is KLC-061.
- Making `remind` read-only — that is KLC-062.
- A background thread / daemon heartbeat (rejected — see design/options.md).
- Any user-visible surfacing of `klc-state`, heartbeats, or push traffic on the
  success path.

## Constraints

> [!CONSTRAINT C-001] source=operator-brief
> Feature-ON is the primary case; feature-OFF heartbeat MUST be a no-op with
> byte-parity (nobody steals in single-user mode).

> [!CONSTRAINT C-002] source=KLC-062
> No per-prompt tracked-tree dirtiness. Within the throttle window the heartbeat
> is read-only; the probe must not trigger legacy-migration writes.

> [!CONSTRAINT C-003] source=KLC-061 + core/skills/state_tx.py
> All holder mutation reaches origin ONLY through `state_tx` (self-heal → pull →
> body → glob-commit + CAS-push, with subtree rollback on failure). No bare
> out-of-`state_tx` write to `meta.holder`.

> [!CONSTRAINT C-004] source=core/skills/holder.py:69,201
> The throttle window MUST be strictly less than `HOLDER_TTL_SECONDS` with margin
> (`HOLDER_TTL_SECONDS // 3` gives 3×), so an active holder's origin
> `heartbeat_at` is always well within the steal TTL.

## Affected modules

- core/skills/holder: add `HEARTBEAT_PUSH_INTERVAL_SECONDS = HOLDER_TTL_SECONDS // 3`
  next to `HOLDER_TTL_SECONDS`. src=core/skills/holder.py:69 (existing
  `heartbeat_holder` at :162 needs no change).
- core/phases/heartbeat: NEW `core/phases/heartbeat.py` with `run(argv) -> int`
  — read-only throttle probe, then `state_tx`-wrapped `heartbeat_holder` when the
  window has elapsed; always exit 0. [!ASSUMPTION if-false=scope-may-expand]
- scripts/klc: add `"heartbeat"` to `LIFECYCLE_CMDS` (src=scripts/klc:92) and to
  `NO_DRAIN_CMDS` (src=scripts/klc:107) — like `remind`, it runs on every prompt
  and must not trigger the Jira drain.
- klc-plugin: NEW `klc-plugin/hooks/heartbeat.py` (mirrors `remind.py`: silent,
  best-effort, always exit 0) + a `UserPromptSubmit` entry in
  `klc-plugin/hooks/hooks.json` (src=klc-plugin/hooks/hooks.json:1).
  [!ASSUMPTION if-false=scope-may-expand]
- core/phases/steal + core/skills/holder (docstrings): the "a live agent keeps it
  fresh with `heartbeat_holder`" claim (src=core/phases/steal.py:5) now names the
  real driver (`klc heartbeat` + the throttled hook).
- tests: `tests/integration/test_heartbeat.py` + a property/fuzz test on a real
  bare-repo `klc-state` fixture.

## Open questions

> [!QUESTION Q-001] blocks=design — RESOLVED (design/adr.md D-1)
> Where does the throttle "last-pushed" marker live? RESOLVED: `heartbeat_at` in
> the CAS-pushed `meta.holder` IS the marker (we only write it when we push), so
> no separate marker file is needed. See design/options.md.

> [!QUESTION Q-002] blocks=operator
> The UserPromptSubmit hook occasionally (≤ once per ~10 min per held ticket)
> incurs a synchronous git pull+CAS-push inside the hook's 10 s timeout, adding
> ~1–2 s latency to that one prompt. Accept this, OR restrict the throttled push
> to explicit `klc` verb invocations (ack/next/status)? The long-single-phase
> (build) case has few verb invocations, so the hook is the more reliable
> trigger; recommendation is to keep the hook + throttle. Operator to confirm.

## Estimate

- complexity: 2  (throttle logic + `state_tx` envelope reuse + hook, spanning
  holder/phases/scripts/plugin; ordering- and concurrency-sensitive)
- uncertainty: 2  (depends on unmerged KLC-061 envelope; the steal-vs-heartbeat
  race needs a real-substrate property test to pin behaviour)
- risk: 2  (writes to the shared `klc-state` branch across collaborators; a wrong
  throttle window or a lost update could make an active holder stealable —
  data-safety across machines; fail-safe-off by default)
- manual: 1  (light manual sanity of the real two-machine flow; the rest is
  autotestable via a bare-repo fixture)
- total: 7
- track: M

DISCOVERY_DONE
