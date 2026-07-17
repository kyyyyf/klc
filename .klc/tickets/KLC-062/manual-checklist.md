---
ticket: KLC-062
kind: manual-checklist
authority: human
---

# Manual checklist — KLC-062

`estimate.manual = 1`. The manual aspect — confirming no per-prompt `meta.json`
churn on the UserPromptSubmit path — is captured deterministically by
byte-identical fixtures that snapshot `meta.json` before and after `remind` /
`status` and assert equality. Each item maps to a spec AC and its automated
evidence; all pass.

## Items

- [x] **AC-1** `klc remind` leaves `meta.json` byte-identical (completable
      discovery ticket). (`test_remind_does_not_write_meta_for_completable_discovery`)
- [x] **AC-1** `klc remind` leaves `meta.json` byte-identical on a legacy-phase
      (`discovery-running`) ticket — the missed path caught in review.
      (discovery-running byte-identical fixture)
- [x] **AC-2** `klc status` performs no legacy-migration write.
      (`test_status_does_not_write_meta_legacy_phase`)
- [x] **AC-3** the real `klc ack` still persists `risk_tags` (the read-only work
      did not disable the legitimate write). (AC-3 regression guard)
- [x] Completion *decision* unchanged with `persist=False` (probe returns the
      same `(ok, advisory)` as the persisting path).
- [x] `scripts/klc` untouched.

## Verification note

The byte-identical fixtures are a stronger and more repeatable check than a
manual "run a prompt and diff meta.json" walkthrough: they pin the no-write
contract for both the discovery and legacy read paths and would fail immediately
on any regression.
