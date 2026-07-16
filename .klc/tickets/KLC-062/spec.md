---
ticket: KLC-062
kind: bug
authority: human
last_generated: 2026-07-16T09:20:00Z
risk_tags: [data]
---

# KLC-062 — `klc remind` must be truly read-only (no per-prompt meta.json churn)

## Goals

- Make `klc remind` a genuinely side-effect-free advisory verb: running it must
  never mutate any ticket's `meta.json`, for ANY ticket in ANY phase, including
  a completable `discovery:work` ticket held by the caller. This is the
  invariant that justifies `remind` living in `NO_DRAIN_CMDS` and being wired
  into a hook that fires on every `UserPromptSubmit`.
- Restore the read-only contract of `klc status` (and the raw-read discipline
  `klc board` already follows): reading a ticket for display must not persist a
  legacy-phase migration back to disk.
- Preserve the existing functional behaviour of `risk_tags` — they must still be
  synced from `spec.md` into `meta.json` at the real completion transition (the
  `ack` path), so no real phase advance loses risk-tag data.
- Close the test gap that let this bug ship: add coverage that drives `remind`
  (and `status`) against write-capable and legacy-phase fixtures and asserts
  `meta.json` is byte-identical afterward.

## Problem / Context

`klc remind` is documented as "a pure read-only advisory verb run on every
UserPromptSubmit" and is excluded from the opportunistic Jira drain precisely
because of that read-only assumption.

FACT: `remind` is listed in `NO_DRAIN_CMDS` with a comment asserting it is
"a pure read-only advisory verb run on every UserPromptSubmit via the hook".
src=scripts/klc:104-107 verified=2026-07-16

FACT: `remind` is registered as a `UserPromptSubmit` hook, so it runs on every
prompt submit. src=klc-plugin/hooks/hooks.json (UserPromptSubmit → remind.py),
tests/integration/test_remind.py:test_hooks_json_has_remind_entry verified=2026-07-16

But `remind` is NOT read-only. Two distinct write paths exist:

### Write path 1 — MEDIUM: `can_complete` mutates meta.json for discovery

FACT: `remind._scan` calls `phase_completion.can_complete(ticket, phase_id)` for
every ticket the current identity holds in a `<phase>:work` state.
src=core/phases/remind.py:118-119 verified=2026-07-16

FACT: for `phase_id == "discovery"`, `can_complete` dispatches to
`can_complete_discovery`. src=core/skills/phase_completion.py:460-461 verified=2026-07-16

FACT: when all discovery gates pass, `can_complete_discovery` calls
`_sync_risk_tags(ticket)` unconditionally before returning success.
src=core/skills/phase_completion.py:172 verified=2026-07-16

FACT: `_sync_risk_tags` unconditionally rewrites `meta.json` via `write_text`
(it reads `spec.md` frontmatter, sets `meta["risk_tags"]`, and serialises the
whole dict back). src=core/skills/phase_completion.py:224-248 (write at :246)
verified=2026-07-16

FACT: on a track downgrade below the intake floor, the same function also
persists `track_source="discovery"` and a `blast_radius` object via
`_lc.write_meta`. src=core/skills/phase_completion.py:152-157 verified=2026-07-16

FACT: `can_complete_discovery_lite` has the identical `_sync_risk_tags` write on
its success path, so a held `discovery-lite:work` ticket has the same defect.
src=core/skills/phase_completion.py:360 verified=2026-07-16

Consequence: a `discovery:work` (or `discovery-lite:work`) ticket held by the
current git identity that already satisfies its completion gates gets `meta.json`
rewritten on EVERY prompt submit — the exact per-prompt git-dirty churn that
`NO_DRAIN_CMDS` was meant to prevent. The reviewer verified this end-to-end:
`klc remind` on a completable `discovery:work` ticket returns the reminder line,
exits 0, and adds `risk_tags` to `meta.json`.

FACT: the same latent write also fires from `klc ack --auto`'s gate-policy probe,
which calls `can_complete` only for its advisory string but discards nothing on
the write side. src=core/skills/gate_policy.py:190 verified=2026-07-16

### Write path 2 — LOW: legacy-phase migration write-back on read

FACT: `lifecycle.read_meta` persists a legacy-phase migration by calling
`write_meta` whenever `_migrate_legacy_phase` rewrites an old-format phase string.
src=core/skills/lifecycle.py:100-105 verified=2026-07-16

FACT: `remind._scan` reads each ticket through `_lc.read_meta`.
src=core/phases/remind.py:101 verified=2026-07-16

FACT: `klc status` reads through `_lc.read_meta` (via `_meta`) despite its module
docstring stating status is read-only, and the completion contract that status
"must never rewrite meta.json". src=core/phases/status.py:41,
core/phases/status.py:1-13 verified=2026-07-16

FACT: `klc board` already avoids this by reading with raw `json.loads` instead of
`read_meta`. src=core/phases/board.py:31 verified=2026-07-16

Consequence: a ticket still carrying an old-format phase string gets silently
migrated-and-written on a plain `status` or `remind` — another read-time write.

### Test gap — LOW: existing tests never exercise the write paths

FACT: `test_remind.py` parks all its completable fixtures in `integrate:work`,
whose `can_complete` is the generic checker (`integrate` declares no outputs), so
no test drives `remind` against a write-capable phase.
src=tests/integration/test_remind.py:8-13,79-99 verified=2026-07-16

FACT: `test_status_does_not_write_meta` uses a modern phase string
(`design:ack-needed`), so it never triggers the legacy-migration write-back.
src=tests/integration/test_status_holder.py:107-115 verified=2026-07-16

## Acceptance Criteria

1. AC-1: `klc remind` never writes `meta.json` for ANY ticket/phase — including a
   completable `discovery:work` ticket held by the caller: meta.json byte-identical
   before/after.
2. AC-2: `klc status` and `klc remind` never persist a legacy-phase migration (no
   read_meta write-back on read); status's read-only contract holds. (Align with
   board.py's raw json.loads or a read-only read variant.)
3. AC-3: `risk_tags` are still persisted at the correct time (the `ack`/completion
   path) — no functional regression to risk-tag behavior for real phase transitions.
4. AC-4 (test plan): add a `discovery:work`-completable fixture asserting
   `meta.json` byte-identical after `klc remind` (mirror the existing
   `test_*_does_not_write_meta` pattern used for board/status); add a legacy-phase
   fixture asserting `status`/`remind` don't rewrite it.
5. AC-5: exit-0/no-crash contract + `NO_DRAIN_CMDS` (remind excluded from Jira
   drain) preserved.

## Non-goals

- Redesigning the completion-detection contract or the `risk_tags` schema. The fix
  keeps `risk_tags` semantics identical; it only controls *when* the write fires.
- Changing the reminder output format, the identity-resolution logic, or the hook
  wiring.
- Removing the latent write from `gate_policy` / `ack --auto` beyond what falls out
  of making the completion probe side-effect-optional (see Constraints C-002).
- A general audit of every other verb for read-time writes (only `status`, `remind`,
  and the `read_meta` path are in scope; `board` is already correct).

## Constraints

> [!CONSTRAINT C-001] source=scripts/klc:104-107
> `remind` must remain in `NO_DRAIN_CMDS` and the hook must keep its exit-0,
> never-crash behaviour. Any new code path in `remind` must degrade to silence on
> error, matching the existing `try/except → continue` discipline.

> [!CONSTRAINT C-002] source=core/skills/phase_completion.py:450-475, core/phases/ack.py:82
> `can_complete` is a foundational, widely-called API (ack, gate_policy, remind,
> its own CLI). Any signature change MUST be backward-compatible via a defaulted
> keyword so existing callers keep today's behaviour; the ack path must continue to
> persist `risk_tags` and any floor-guard audit exactly as before.

> [!CONSTRAINT C-003] source=core/skills/lifecycle.py:100-105
> `read_meta`'s in-memory migration must still happen so callers see the modern
> phase string for correct display/logic; only the *write-back* is suppressed on the
> read-only path. A defaulted keyword must preserve the current persist-on-migrate
> behaviour for all existing callers.

## Affected modules

- core/skills: `phase_completion.py` (make the completion probe side-effect-optional)
  and `lifecycle.py` (add a read-only, non-persisting read path). Foundational —
  broad fan-in.
- core/phases: `remind.py` and `status.py` (consume the read-only variants);
  `ack.py` is verified to keep persisting `risk_tags` at the real transition.
- tests: new integration coverage (`test_remind.py`, `test_status_holder.py`).

Blast-radius input (from `.klc/index/modules.json` reverse edges):
`core/skills` has `depended_by = [core/phases, klc-plugin, scripts, tests]` — a
large fan-in, so an incompatible change to `can_complete` / `read_meta` would
ripple widely. This is contained by C-002/C-003 (backward-compatible defaulted
keywords only), but the fan-in is why this ticket is scored at track M rather than
downgraded: `risk` is elevated because the touched symbols are on the ack (data
mutation) path.

## Open questions

None blocking. The three fix directions from the reviewer are captured as approaches
below; the pick is recorded and refined in `design/options.md`. The exact naming of
the read-only helpers is a design-phase detail, not a discovery blocker.

## Approaches considered

Full trade-off detail lives in `design/options.md`. Shortlist:

- Approach A — side-effect-optional probe (`persist=` keyword): thread a defaulted
  `persist: bool = True` through `can_complete` / `can_complete_discovery` /
  `can_complete_discovery_lite`, gating the two write sites (`_sync_risk_tags` and
  the floor-guard `write_meta`). `remind` calls with `persist=False`; `ack` keeps the
  default. Pair it with a non-persisting read (`read_meta` gains
  `persist_migration: bool = True`; add a thin `read_meta_ro` used by
  `status`/`remind`).
- Approach B — relocate persistence to ack: make the whole `can_complete` family purely
  read-only and move `_sync_risk_tags` + the floor-guard audit write into `ack.py`
  explicitly.
- Approach C — special-case discovery in remind: in `remind`, skip the writing checker for
  `discovery`/`discovery-lite` (or substitute a hand-rolled read-only check).

Picked: A — side-effect-optional probe — it fixes the root cause on every read-only
caller (not just `remind`), keeps blast radius minimal via backward-compatible
defaulted keywords (C-002/C-003), and still persists `risk_tags`/audit at the real
`ack` transition (AC-3). B is cleaner in principle but the floor-guard relocation is
fiddly and higher-risk on a foundational path; C is narrow, misses `discovery-lite`
and `gate_policy`, and duplicates gate logic.

## Estimate

- complexity: 2
- uncertainty: 1
- risk: 3
- manual: 1
- total: 7
- track: M
