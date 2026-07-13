---
ticket: KLC-059
kind: review-report
authority: human
reviewed_by: general-purpose subagent (fresh, no conversation context) + codex exec review --base main (3 rounds)
reviewed_at: 2026-07-13
review_depth: full
branch: feature/klc-059-remind
---

# Review report — KLC-059

## Summary

`klc remind` + UserPromptSubmit hook. Fresh `general-purpose` subagent (per
CLAUDE.md) + `codex exec review --base main` over three fix rounds. The fresh
review was essentially clean (1 LOW); codex drove out a sequence of real
contract/robustness issues on the silent-advisory verb and its hook, all fixed
with verified RED→GREEN cycles. 12 tests pass.

## Verdict

APPROVED — all findings fixed; the always-exit-0 / silent-advisory contract and
AC-1..5 hold. 12 tests.

## Findings by round (all fixed)

### Round 1 — fresh + codex
- **codex P2** non-dict `holder` → `AttributeError` (violated exit-0 contract) → validate holder is a dict / skip malformed.
- **codex P2** hook forwarded child stderr on failure → capture output, forward only stdout on clean (rc=0) exit; else silent.
- **fresh LOW** dead `_ = "--statusline" in ...` no-op → removed (flag still accepted, no-op per AC-5).

### Round 2 — codex re-review
- **P2** git identity read from process cwd, not `PROJECT_ROOT` → hook/statusline running elsewhere missed reminders. **P2** build-completion git-log searched in cwd. Both fixed: `run()` resolves `project_root()` and `os.chdir()`s into it for the scan (restore in `finally`), so identity + `can_complete` target the project repo.

### Round 3 — codex re-review
- **P2** `klc remind` went through the dispatcher's opportunistic `_drain_jira_queue()` → every prompt submit could perform Jira writes/timeouts → added `NO_DRAIN_CMDS=("jira-sync","remind")`; remind is now side-effect-free.
- **P2** non-string `phase` → `AttributeError` → validate `phase` is str before string ops.

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| AC-1 | PASS | nothing completable-held → no output, exit 0 |
| AC-2 | PASS | held + can_complete + `:work` → one line `KLC-xxx <phase> is done — run klc ack` (exact, em-dash) |
| AC-3 | PASS | other-holder → silently skipped |
| AC-4 | PASS | hooks.json UserPromptSubmit entry; hook exits 0 in ALL cases (incl. child failure, no stderr leak) |
| AC-5 | PASS | `--statusline` same line; no output when idle |

## Final state

`PROJECT_ROOT=<tmp> python3 -m pytest tests/integration/test_remind.py -v` →
12 passed. `klc remind` is read-only, silent-by-default, always exit 0, no Jira
side effect, robust to malformed tickets, and operates against `PROJECT_ROOT`.
