---
ticket: KLC-060
authority: hybrid
last_generated: 2026-06-27T08:45:00Z
---

# Test plan — KLC-060

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 (board, holder present) | acceptance | tests/integration/test_board_holder.py::test_board_text_shows_holder_id | text output contains the holder id |
| AC-1 (board, --json, holder present) | acceptance | tests/integration/test_board_holder.py::test_board_json_shows_holder_id | JSON record carries `holder_id` key |
| AC-1 (board, holder absent) | acceptance | tests/integration/test_board_holder.py::test_board_no_holder_unchanged | row unchanged from today; no crash, no empty artifact |
| AC-2 (status, ack-needed + holder) | acceptance | tests/integration/test_status_holder.py::test_status_ack_needed_shows_waiting_hint | annotation contains "waiting on ack from <id>" |
| AC-2 (status, non-ack-needed + holder) | acceptance | tests/integration/test_status_holder.py::test_status_other_state_shows_holder_no_waiting | holder id shown, "waiting on ack" wording absent |
| AC-2 (status, holder absent) | acceptance | tests/integration/test_status_holder.py::test_status_no_holder_no_crash | renders normally; no crash, no empty artifact |
| AC-3 (read-only, no writes) | acceptance | tests/integration/test_board_holder.py::test_board_does_not_write_meta | meta.json mtime unchanged after `klc board` |
| AC-3 (read-only, no writes) | acceptance | tests/integration/test_status_holder.py::test_status_does_not_write_meta | meta.json mtime unchanged after `klc status` |
| AC-3 (missing holder, no KeyError) | acceptance | tests/integration/test_board_holder.py::test_board_no_holder_no_key_error | null/missing holder never raises KeyError |
| AC-3 (--json valid JSON when no holder) | acceptance | tests/integration/test_board_holder.py::test_board_json_no_holder_valid_json | `--json` output parseable even when holder absent |

## Edge cases

- `holder` key is present but `id` sub-key is missing or null — display should degrade gracefully (show nothing or a safe placeholder) rather than crash.
- `holder` key is present with an empty string `id` — treat the same as absent.
- Ticket in `ack-needed` state with **no** holder — status renders the `ack-needed` annotation without the "waiting on ack from" suffix (no crash).
- Multiple tickets on the board, some with a holder and some without — only the holder rows are annotated; non-holder rows are unchanged.
- `--json` output: the holder field must never appear as `None` in JSON (use `null` or omit the key); the output must be parseable by `json.loads`.

## Regression scenarios

- `klc board` text output layout does not regress for tickets that have no holder (column widths, grouping by phase, key/track/kind fields — all unchanged).
- `klc status <ticket>` for a ticket in every non-ack-needed phase state (`work`, `ack`) still renders correctly when holder is absent — none of the existing annotation branches crash.
- `klc board --json` schema: existing consumers that do not expect a `holder_id` field continue to work because the field is absent (not null) when no holder exists.

## Manual checklist

<!-- estimate.manual = 0; no manual checklist required -->

## Detailed coverage
<!-- TBD — populated in phase 4 after Design -->

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
