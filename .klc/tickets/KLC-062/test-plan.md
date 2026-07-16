---
ticket: KLC-062
authority: hybrid
last_generated: 2026-07-16T09:35:00Z
---

# Test plan — KLC-062

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/integration/test_remind.py::test_remind_does_not_write_meta_for_completable_discovery | fabricate a `discovery:work` ticket held by the caller with a complete `spec.md` + `meta.json` that pass every discovery gate (incl. risk_tags in frontmatter); snapshot `meta.json` bytes; run `klc remind`; assert reminder line printed, exit 0, and `meta.json` byte-identical |
| AC-2 | acceptance | tests/integration/test_status_holder.py::test_status_does_not_write_meta_legacy_phase | fabricate a ticket whose `meta.json:phase` is a legacy string (e.g. `design-pending`); snapshot bytes; run `klc status`; assert exit 0, display shows the migrated phase, and `meta.json` byte-identical (no migration write-back) |
| AC-2 | acceptance | tests/integration/test_remind.py::test_remind_does_not_write_meta_legacy_phase | same legacy-phase fixture, held by the caller in a completable legacy `<phase>:work`; run `klc remind`; assert exit 0 and `meta.json` byte-identical |
| AC-3 | acceptance | tests/integration/test_ack_risk_tags.py::test_ack_discovery_persists_risk_tags | drive a real `discovery` → ack transition (`klc ack --pick 1`) on a ticket whose `spec.md` frontmatter carries `risk_tags`; assert `meta.json:risk_tags` equals the spec's tags after the ack (persistence still happens at the ack/completion path) |
| AC-4 | acceptance | tests/integration/test_remind.py::test_remind_does_not_write_meta_for_completable_discovery, tests/integration/test_status_holder.py::test_status_does_not_write_meta_legacy_phase | the two byte-identical fixtures mandated by AC-4 (discovery-completable for remind; legacy-phase for status/remind), mirroring the existing `test_*_does_not_write_meta` pattern |
| AC-5 | acceptance | tests/integration/test_remind.py::test_remind_does_not_drain_jira_queue, ::test_hook_always_exits_zero, ::test_remind_fires_when_held_and_completable | existing suite re-run: `remind` stays in `NO_DRAIN_CMDS` (queue byte-identical), hook exits 0, reminder still fires for a completable held ticket |

## Edge cases

- Discovery ticket that is held but NOT yet completable (e.g. `spec.md` missing a required section): `remind` must be silent AND must not write `meta.json` — the probe returns False before reaching any write site.
- Discovery ticket held by a DIFFERENT identity: skipped before `can_complete` is even called; no read-only probe, no write.
- `discovery-lite:work` completable ticket held by the caller: same `_sync_risk_tags` write site (`phase_completion.py:360`) — assert `remind` leaves `meta.json` byte-identical (guards against fixing only the `discovery` path).
- Legacy-phase string that has NO mapping in `_LEGACY_MAP` (e.g. a garbage phase): `_migrate_legacy_phase` returns False, so no write either way; `status`/`remind` must still not crash.
- Modern-phase ticket (already `<phase>:<state>` form): `read_meta` never migrates, so this path is unaffected — a regression check that the read-only variant does not alter modern tickets.
- `spec.md` absent or unreadable during the probe: the read-only completion check must degrade to "not completable" without raising and without writing (matches remind's `try/except → continue`).
- Track-downgrade floor-guard write (`phase_completion.py:152-157`): on the read-only path this second write site must also be suppressed; a discovery ticket that would trigger the audit write must stay byte-identical under `remind`.

## Regression scenarios

- tests/integration/test_remind.py — the full existing suite (silent-when-nothing, fires-when-completable, other-holder skip, non-dict/non-string robustness, statusline parity, hook exit-0, no-Jira-drain, project-root-not-cwd) must continue to pass unchanged.
- tests/integration/test_status_holder.py — existing holder-annotation and `test_status_does_not_write_meta` (modern phase) scenarios must still pass.
- tests/integration/test_board_holder.py — `board`'s existing raw-read `does_not_write_meta` behaviour is the reference discipline; must remain green.
- Any test exercising `klc ack` on a real `discovery` completion (manual-completion detection at `ack.py:82`) must still observe `risk_tags` written and the floor-guard audit persisted — the `persist=True` default path is unchanged (AC-3).
- `klc ack --auto` gate-policy tests (KLC-045, tests/integration/test_gate_policy.py): the advisory `can_complete` probe at `gate_policy.py:190` switching to `persist=False` must not change any gate verdict or advisory string.

## Manual checklist (populated iff estimate.manual ≥ 2)
<!-- estimate.manual = 1 → no manual checklist required -->

## Detailed coverage
<!-- TBD — populated in phase 4 after Design -->

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
