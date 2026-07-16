---
ticket: KLC-057
authority: human
last_generated: 2026-07-16T00:00:00Z
---

# Retrospective — KLC-057

## What happened (facts, not opinions)

> [!FACT F-R1] src=meta.json:estimate
> estimate = {complexity:2, uncertainty:2, risk:2, manual:1, total:7}, track=M,
> risk_tags=[data, migration]. The integration spine of the KLC-053..060
> multi-user epic — wires state_sync/identity/holder into intake/ack/next.

> [!FACT F-R2] src=review-report.md, branch history
> The initial build passed its own tests (18) but review found the feature-ON
> path was NOT data-safe: every fix round (codex + fresh) surfaced a NEW
> code-path of the same class (mutation-outside-tx / validate-before-pull),
> because the tests STUBBED state_sync, hiding the real git interaction.

> [!FACT F-R3] src=branch history (35 commits)
> Progression: build (16) → design-pass (self-healing state_tx envelope) →
> harden1..6 → fuzz gate (sequential + true-multiprocess). Point-fixes did not
> converge; the design-pass + a fuzz/property harness did.

> [!FACT F-R4] src=tests/integration/test_klc057_fuzz*.py
> The convergence gate: 7 invariants asserted after every op; sequential 750
> ops + true-concurrent 40-round barrier-forced CAS-race soak → 0 violations.
> The one violation the concurrent harness ever found (intake --force holder-auth)
> was fixed (harden6) and its scenario flipped to a passing assertion.

## What went well

- **Two independent reviewers (codex + fresh) with different biases repeatedly
  found real, non-overlapping issues.** On several rounds codex graded a finding
  P1 that fresh graded LOW (or vice-versa) — the disagreement itself surfaced the
  right severity discussion (e.g. holder-mitigation of the ack stale-validation).
- **Escalating from point-fixes to a design-pass was the correct call.** Once the
  reviews stopped converging (each round finding the next unwrapped path), a
  self-healing envelope + "commit the whole ticket subtree" killed the class
  structurally instead of instance-by-instance.
- **The fuzz/property gate is the durable win.** It converted "review keeps
  finding corners" into a systematic, repeatable proof — and pinned the last real
  bug (intake --force holder-auth) with a deterministic reproducer. It stays as a
  permanent regression gate.
- **Feature-OFF byte-parity held throughout** — default single-user KLC was never
  at risk while the multi-user machinery was hardened behind an opt-in gate.

## What went wrong

- **Stubbed tests masked the real integration failure.** The build's tests
  stubbed `state_sync` to no-ops, so the actual `git pull --rebase`-on-dirty-tree
  crash and the deadlock/rollback classes were invisible until codex reasoned
  about real git behaviour. A real-bare-repo test existed only for the happy path.
- **A specified design invariant was itself wrong.** The first self-heal rule
  ("dirty tree = crash artifact, discard it, remote is truth") DESTROYED
  legitimate in-progress tracked artifacts — a data-loss flaw introduced by the
  fix, caught by the next review. Corrected to stash-preserve.
- **The transaction boundary fought the verbs' existing structure.** intake/ack/
  next mutate tracked `.klc` at many scattered points (index append, supersede
  moves, manual-completion set_state, jira hook, --force); wrapping fragments
  one-at-a-time is why it took a design-pass to make the envelope authoritative.

## Lessons (imperative)

- For any feature whose value IS the real external interaction (git CAS, network,
  fs), write a REAL-substrate test (local bare repo) for the CONFLICT/rollback
  paths from day one — never let the whole feature be validated only through a
  stub. Stubs prove the wiring, not the behaviour.
- When incremental review⇄fix stops converging (round N keeps finding the next
  instance of one class), STOP patching and either (a) close the class at a single
  choke-point / envelope, and/or (b) build a property/fuzz gate that asserts the
  invariants across random inputs — one harness finds the whole class, a review
  finds one instance.
- Treat "the remote/pulled state is truth, discard local" invariants with
  suspicion when local uncommitted state can be legitimate work — prefer
  preserve-and-reconcile (stash/commit) over discard.
- Keep two independent review sources for cross-cutting infrastructure; their
  severity disagreements are signal, not noise.

## Proposed knowledge-base updates

- Few-shot for `core/agents/test-planner.md` / `test.md`: "when a ticket's value
  is a real external side effect (git/network/fs coordination), the test plan
  MUST include a real-substrate conflict/rollback test, not only a stubbed one;
  and for concurrency/coordination features, a property/fuzz harness asserting
  invariants across random (and truly-concurrent) op sequences."
- Few-shot for `core/agents/review/*` : "for a transaction/envelope over existing
  rich verbs, sweep for EVERY mutation site and validate-before-commit path; if
  fixes keep finding new sites, recommend closing the class at the envelope."
- No `reviewer-allowlist.yml` changes — every finding was a real bug.

## Estimate accuracy

- estimate.total = 7 (M). Build effort matched ~M; the REVIEW/hardening effort
  vastly exceeded a typical M ticket (design-pass + 6 harden rounds + a fuzz
  harness). The estimate model captures build complexity but not
  "integration-spine coordination-correctness" cost — a signal that
  integration/coordination tickets warrant a risk multiplier or a mandatory
  fuzz-gate line item in the plan.
