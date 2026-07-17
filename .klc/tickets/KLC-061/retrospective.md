---
ticket: KLC-061
authority: human
last_generated: 2026-07-17T00:00:00Z
---

# Retrospective — KLC-061

## What happened (facts, not opinions)

> [!FACT F-R1] src=meta.json:estimate
> estimate = {complexity:2, uncertainty:1, risk:2, manual:1, total:6}, track=M,
> risk_tags=[data, migration]. Wraps the state-mutating verbs that predate the
> KLC-057 envelope (`ship`/`steal`/`abort`/`jump`/`jira` reconcile) into the
> `acquire_lock → state_tx → holder` envelope.

> [!FACT F-R2] src=review-report.md, branch history
> Merged `f833d5a` (PR #65). Two independent reviewers (fresh general-purpose +
> `codex exec review`) found non-overlapping real gaps: codex the missing
> holder-auth on `jira reconcile`, fresh the missing per-ticket lock. A follow-up
> fix (stale same-user holder not refreshed) surfaced on the fix re-review.

> [!FACT F-R3] src=build-log.md, review-report.md
> Every finding was fixed TDD (RED→GREEN); the delicate holder-liveness fix got a
> scoped codex re-review of the fix delta (clean). One item was a ratified
> descope (advisory `jira sync --apply`) → follow-up KLC-065.

> [!FACT F-R4] src=tests
> test_klc061_wrap_verbs.py 23 passed; concurrency fuzz extended (scenario-5
> stale-steal, scenario-6 ship-vs-ack) 0 invariant violations; full regression
> 762 passed; feature-OFF byte-parity intact.

## What went well

- **Two independent reviewers with different biases caught non-overlapping real
  bugs.** codex flagged the holder-authorization gap on `jira reconcile`; the
  fresh reviewer flagged the missing per-ticket lock. Keeping both sources is
  cheap insurance for cross-cutting infrastructure.
- **`ship`-as-delegation was the right structural call.** Routing `ship` through
  `ack.run` (+`next.run`) instead of re-implementing the advance killed the
  pre-existing double-advance bug (`apply_ack` auto-advances) as a side effect,
  and inherited the KLC-057 envelope for free (ADR D-002).
- **Scoped re-review of the fix delta caught a second-order bug.** The
  holder-auth fix left a stale same-user holder unrefreshed (immediately
  stealable); re-reviewing only the fix delta surfaced it before merge.
- **Feature-OFF byte-parity held throughout** — single-user KLC was never at risk.

## What went wrong

- **The envelope alone was not the whole fix.** Wrapping each verb in `state_tx`
  looked sufficient, but each verb also needed its companion guards — the
  per-ticket lock, holder-authorization, and deferred-Jira. Moving only the
  envelope and not all four guards together left real gaps (the `jira reconcile`
  no-lock / no-holder-auth finding).
- **Wrapping scattered verbs one-at-a-time is gap-prone.** The verbs mutate
  tracked state at different points with different pre-existing shapes, so a
  per-verb sweep is easy to under-do; the fuzz gate + two reviewers were needed
  to prove completeness.

## Lessons (imperative)

- When wrapping an existing verb in a transaction envelope, move the **whole
  guard set together** — envelope + per-ticket lock + holder-authorization +
  deferred side effects (Jira) — never the envelope alone. Enumerate the guards
  the reference verbs (`ack`/`next`) already have and check each new verb against
  the full set.
- After fixing a delicate coordination bug (holder/liveness), re-review the
  **fix delta** specifically — the fix can introduce a second-order bug (here, an
  unrefreshed same-user holder) that the original review never saw.
- Keep two independent review sources for cross-cutting infrastructure; their
  non-overlapping findings are signal, not redundancy.

## Proposed knowledge-base updates

- Few-shot for `core/agents/review/*`: "when a diff wraps an existing verb in a
  transaction/lock envelope, verify the verb also carries the full companion
  guard set the reference verbs have (lock + holder-auth + deferred side
  effects), not just the envelope."
- No `reviewer-allowlist.yml` changes — every finding was a real bug; the single
  non-fix was a deliberately-ratified descope (KLC-065), not a false positive.

## Estimate accuracy

- estimate.total = 6 (M). Build effort matched ~M. The review/fix effort was a
  little above a typical M because the guard-completeness gaps needed two
  reviewers plus a fix-delta re-review to close — consistent with the KLC-057
  signal that coordination/state_tx work carries a review-cost tail the estimate
  model under-weights.
