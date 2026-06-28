---
ticket: KLC-056
authority: hybrid
last_generated: 2026-06-27T08:30:00Z
---

# Test plan — KLC-056

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_holder.py::test_acquire_on_free_phase | Assert holder dict returned with correct id, machine, since |
| AC-2 | acceptance | tests/test_holder.py::test_acquire_refused_when_held_by_other | Assert HolderConflictError raised; check .holder unchanged |
| AC-3 | acceptance | tests/test_holder.py::test_acquire_idempotent_same_holder | Assert same since returned; no overwrite |
| AC-4 | acceptance | tests/test_holder.py::test_release_by_holder_clears_field | Assert meta.holder is null; return value True |
| AC-5 | acceptance | tests/test_holder.py::test_release_refused_when_held_by_other | Assert HolderConflictError raised; meta.holder unchanged |
| AC-6 | acceptance | tests/test_holder.py::test_release_noop_when_null | Assert returns False; no write occurs |
| AC-7 | acceptance | tests/test_holder.py::test_no_direct_filesystem_io | Patch lifecycle.read_meta/write_meta; assert no open() calls in holder.py |
| AC-8 | acceptance | tests/test_holder.py::test_identity_shape_and_since_format | Assert since is ISO-8601 UTC; machine field stored |

## Edge cases
- Holder dict missing the `machine` key — function must raise ValueError, not silently store incomplete holder.
- `since` must be a UTC timestamp (ending in Z), not localtime.
- identity id empty string — treat as absent holder (raise ValueError on acquire).
- Concurrent acquire simulation: two acquire calls on same in-memory dict (not a git test) — second must see conflict.

## Regression scenarios
- lifecycle.read_meta / write_meta round-trip still works after holder field added to meta (no schema break).
- Existing meta.json without a `holder` key is treated as free phase (no KeyError).

## Manual checklist (populated iff estimate.manual ≥ 2)
(none — estimate.manual = 0)

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
