---
ticket: KLC-064
authority: human
last_generated: 2026-07-17T00:00:00Z
---

# Retrospective — KLC-064

## What happened (facts, not opinions)

> [!FACT F-R1] src=meta.json:estimate
> estimate = {complexity:2, uncertainty:2, risk:2, manual:1, total:7}, track=M,
> risk_tags=[data]. Gives `heartbeat_holder` its first production caller (a
> `klc heartbeat` verb + UserPromptSubmit hook), feature-ON and throttled, so
> `steal_holder`'s TTL steal-safety stops being inert.

> [!FACT F-R2] src=design/adr.md, review-report.md
> The first design (S, feature-OFF, write-every-prompt) was sent back at
> design-pass and re-scoped S→M. A heartbeat's value is entirely multi-user, and a
> write-every-prompt shape reintroduces the churn KLC-062 removes.

> [!FACT F-R3] src=review-report.md
> The fresh reviewer found NO HIGH/MEDIUM — the concurrency design was confirmed
> sound (throttle marker reflects origin; doubly-safe race guard = pull
> StaleStateError + in-body ownership recheck; CAS one-winner). codex found one P2
> (scan aborted on one ticket's lock failure); two LOWs from fresh. All fixed TDD.

> [!FACT F-R4] src=tests
> test_heartbeat.py 15 passed; test_heartbeat_race.py real bare-repo two-worktree
> CAS race — both winners, full coherence invariant, stable at 40 rounds; full
> regression 812 passed; feature-OFF byte-parity. Merged `8414526` (PR #68).

## What went well

- **Design-pass caught a bad shape before any code was written.** Rejecting the
  S/feature-OFF/write-every-prompt design saved building something worthless
  single-user that would have re-broken KLC-062's no-churn contract.
- **The clean shape reused existing primitives.** `heartbeat_at` doubling as the
  throttle "last-pushed" marker (no separate marker file), window = `TTL/3`,
  read-only within the window, and the write+push riding the KLC-061 `state_tx`
  envelope — all composition, no new machinery.
- **The concurrency design was confirmed sound by a fresh reviewer**, and the real
  bare-repo steal-vs-heartbeat race (40-round soak) turned that judgement into a
  repeatable coherence proof.

## What went wrong

- **The initial estimate mistook coordination for wiring.** "Add a caller for an
  existing function" looked like S wiring, but it touches `state_tx`, the throttle
  contract, and a real steal-race — genuinely M coordination. LOC was small; the
  correctness surface was not.
- **A small best-effort scan had a real starvation bug.** Aborting the whole scan
  on one ticket's `acquire_lock` failure (codex P2) meant a single locked ticket
  could silently stop every later held ticket from being refreshed.

## Lessons (imperative)

- Track/estimate by **correctness surface, not LOC**: anything that touches
  `state_tx`, holder/heartbeat, or concurrency should floor at M regardless of how
  few lines it adds — a risk-based track floor for "touches state_tx / concurrency"
  would have caught this at intake.
- In a best-effort multi-item scan, isolate each item (`try/except: continue`) so
  one item's failure cannot starve the rest.
- For a feature whose entire value is multi-user, validate the design against the
  multi-user contract at design-pass (does it work feature-ON? does it respect
  sibling no-churn/no-bare-write contracts?) before building.

## Proposed knowledge-base updates

- Few-shot / rule for track classification (`core/agents/intake-triage.md` /
  discovery): "a change that touches `state_tx`, holder/heartbeat, or concurrency
  floors at track M regardless of LOC — the correctness surface, not the diff
  size, sets the track."
- No `reviewer-allowlist.yml` changes — every finding was a real issue.

## Estimate accuracy

- estimate.total = 7 (M) after the design-pass re-scope. The initial instinct was
  S; the re-scope to M was correct and the build/review effort matched M. The
  drift was caught at design-pass rather than in flight — the right place — but a
  risk-based track floor should have set M at intake so the design-pass re-scope
  was confirmation, not correction.
