---
ticket: KLC-058
kind: review-lite-report
authority: human
reviewed_by: general-purpose subagent (fresh, no conversation context) + codex exec review --base main (3 rounds)
reviewed_at: 2026-07-13
review_depth: full
branch: feature/klc-058-steal-heartbeat
---

# Review-lite report — KLC-058

## Summary

`klc steal` + `heartbeat_holder`. Fresh `general-purpose` subagent (per
CLAUDE.md) + `codex exec review --base main` over three fix rounds. Core logic
(age from `heartbeat_at` else `since`, warning-before-takeover via `on_takeover`,
lock-serialized steal, field-preserving heartbeat) was sound; the reviews drove
out edge/robustness/contract fixes, all with verified RED→GREEN. 66 tests pass.

## Verdict

APPROVED — all findings fixed; AC-1 (TTL-gated steal + warning) and AC-2
(heartbeat_holder) hold at both the `holder.py` and `lifecycle.py` entry points.

## Findings by round (all fixed)

### Round 1 — fresh (5 LOW)
- **L1** `--ttl-minutes 0`/negative stole a live holder → `run()` rejects ttl ≤ 0.
- **L2** non-string/malformed `heartbeat_at` → uncaught `AttributeError` / un-stealable → `_parse_iso_z` raises `ValueError` (not AttributeError); `_holder_age_seconds` falls back to `since`; both corrupt → clean typed error, no traceback.
- **L4** `≥`/`→` glyphs crashed under C locale → ASCII (`>=`, `->`).
- **L3** pre-existing TOCTOU in `artefacts.acquire_lock` → deferred (shared lock layer, not KLC-058; see `.klc/wave1-followup-hardening.md`).
- **L5** test gaps → covered by the L1/L2 tests.

### Round 2 — codex re-review
- **P2** AC-2 names `lifecycle.py`, but `heartbeat_holder`/`steal_holder` lived only in `holder.py` → added thin delegating wrappers in `lifecycle.py` (function-level import to avoid the holder↔lifecycle cycle); both entry points now work.

### Round 3 — codex re-review
- **P2** library `steal_holder` didn't enforce a positive TTL (only the CLI did) → a non-CLI caller with `ttl_seconds ≤ 0`/NaN/inf could overwrite a live holder → guard inside `steal_holder` raises `ValueError` on any non-positive/non-finite TTL before reading state.

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| AC-1 | PASS | within-TTL → non-zero + clear msg + holder unchanged; expired → warning-before-takeover + overwrite; `--ttl-minutes` guarded, library TTL guarded; `test_holder_steal.py` |
| AC-2 | PASS | `heartbeat_holder` updates only `heartbeat_at` (ISO-Z), preserves fields, `ValueError` when no holder; callable via `holder.` AND `lifecycle.` |

## Final state

`python3 -m pytest tests/test_holder_steal.py tests/test_holder.py -q` → 66 passed.
Placement note: `heartbeat_holder`/`steal_holder` implemented in `core/skills/holder.py`
(with the holder family) and re-exported via `core/skills/lifecycle.py`.
