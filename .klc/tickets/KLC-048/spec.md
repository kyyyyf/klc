---
ticket: KLC-048
kind: tech
authority: human
risk_tags: []
---

# KLC-048 — Happy-path guide

## Goals

Ship `docs/happy-path.md`: a single-screen walkthrough of one ticket from `klc intake`
to `archived`, listing the exact command at each gate so a newcomer can drive the process
without reading the full `docs/process.md`.

## Acceptance Criteria

- [ ] AC-1: `docs/happy-path.md` exists and walks a single clean S-track ticket end to end
  (intake, discovery-lite, build, review, integrate, then archived) with the literal `klc`
  command for each transition. The flow is ack-only: each forward `klc ack` also advances to
  the next phase's `:work` (no `klc next`). It notes in one line that `observe` and `learn`
  are condition-gated and run only when their conditions apply (risk tags / failure signals),
  so a clean S ticket reaches `archived` on the `klc ack` that confirms `integrate`
  (observe/learn condition-skipped) — not via a `klc next` or a `learn` pick.
- [ ] AC-2: Each step names the artifact produced and the `klc ack` pick that advances it.
- [ ] AC-3: The guide fits one screen (at most 60 lines of body) and links to
  `docs/process.md` for the full contract.

## Affected

- `docs/happy-path.md` (new).

## Estimate

| Axis | Score |
|------|-------|
| total | 1 |
