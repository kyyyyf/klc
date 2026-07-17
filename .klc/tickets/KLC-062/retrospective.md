---
ticket: KLC-062
authority: human
last_generated: 2026-07-17T00:00:00Z
---

# Retrospective — KLC-062

## What happened (facts, not opinions)

> [!FACT F-R1] src=meta.json:estimate
> estimate = {complexity:2, uncertainty:1, risk:3, manual:1, total:7}, track=M,
> risk_tags=[data]. Makes `klc remind` truly read-only by threading a
> `persist`/`persist_migration` flag from the entry points through `can_complete*`
> to `read_meta`, plus `read_meta_ro`.

> [!FACT F-R2] src=review-report.md
> The build's own tests passed, but a fresh general-purpose reviewer and
> `codex exec review` both found the ticket's core bug still live: the `persist`
> flag missed the `read_meta` call inside `can_complete_discovery`/`_lite`, so a
> legacy-phase discovery ticket was still migrated-and-written on the read-only
> path.

> [!FACT F-R3] src=review-report.md, build-log.md
> Root cause of the miss: the pre-existing legacy test used an integrate-post
> fixture, which routes to the generic completion checker (never reads meta), so
> it never exercised the discovery read path. Fixed by threading
> `persist_migration` into both internal reads + a `discovery-running`
> byte-identical fixture (RED→GREEN).

> [!FACT F-R4] src=tests
> Targeted 45 passed; regression band 278 passed. Byte-identical fixtures for
> `remind` (discovery + legacy) and `status`; AC-3 guard: real `ack` still
> persists risk_tags. `scripts/klc` untouched. Merged `0644cfa` (PR #66).

## What went well

- **Two external reviewers both traced every write path from the entry point**
  and converged on the same real bug — the one the ticket exists to fix — that
  the build's own tests missed.
- **The fix stayed at the source.** Rather than special-casing `remind`, the
  `persist` flag threads through the shared completion machinery, so `status`,
  `gate_policy`, and `remind` all get the read-only guarantee from one change.
- **Byte-identical fixtures are the right shape for a no-write contract** — they
  pin the exact property (meta.json unchanged) rather than a proxy.

## What went wrong

- **An internal review with the wrong fixture hid the exact target bug.** The
  legacy test used an integrate-post ticket, which never reaches the discovery
  read path, so it "passed" while the discovery-phase churn remained. Validating
  against the AC as written (not against every reachable code path) let the bug
  survive the build's own tests.

## Lessons (imperative)

- When closing a "no-write" / "read-only" contract, **enumerate every mutation
  reachable from the entry point** and add a byte-identical snapshot test for
  each reachable branch — do not trust a single fixture that may route around the
  path the ticket targets.
- Choose the test fixture to exercise the *specific* code path under change
  (here: a discovery-phase, legacy-phase ticket), not a convenient generic one
  that short-circuits it.

## Proposed knowledge-base updates

- Few-shot for `core/agents/test-planner.md` / `test.md`: "for a read-only /
  no-write contract, add a byte-identical (before==after) fixture for EACH
  reachable code path (each phase/state that routes differently), not one generic
  fixture — a fixture that routes around the target path gives false confidence."
- No `reviewer-allowlist.yml` changes — the finding was a real bug.

## Estimate accuracy

- estimate.total = 7 (M), risk=3 reflecting the churn/data-safety concern. Build
  effort matched ~M; review found one real bug that build tests missed, so the
  review round was load-bearing but not oversized. The risk=3 rating was
  well-placed — the bug that slipped past build tests was exactly the data-churn
  risk the estimate flagged.
