---
ticket: KLC-059
kind: feature
authority: agent
track: S
risk_tags: [user-facing]
---

## Goals
Add `klc remind` — a silent-by-default CLI verb that emits one reminder line when the current git identity holds a ticket phase in `:work` state and `phase_completion.can_complete` returns True, delivered automatically via a Claude Code UserPromptSubmit hook.

## Acceptance Criteria
- [ ] AC-1: `klc remind` with no completable-held ticket produces no output and exits 0.
- [ ] AC-2: `klc remind` with a ticket where the current git identity is the `holder` AND `phase_completion.can_complete(ticket, phase) == True` AND the phase state is `:work` emits exactly one line of the form `KLC-xxx <phase> is done — run klc ack` and exits 0.
- [ ] AC-3: `klc remind` does not fire for tickets held by a different git identity (i.e. holder.id != current git user.email); those are silently skipped.
- [ ] AC-4: A `UserPromptSubmit` hook entry in `klc-plugin/hooks/hooks.json` invokes `klc remind`; the hook exits 0 (non-blocking) in all cases, including when `klc remind` cannot locate a ticket.
- [ ] AC-5: An optional statusline mode (`klc remind --statusline`) emits the same reminder line to stdout for use in shell prompts; no output when nothing to do.

## Affected
klc-plugin/hooks: `klc-plugin/hooks/remind.py` — new script, `src=klc-plugin/hooks/remind.py` [!ASSUMPTION if-false=scope-may-expand] file does not exist yet; path chosen to match gate.py sibling pattern
klc-plugin/hooks: `klc-plugin/hooks/hooks.json`, src=klc-plugin/hooks/hooks.json:1 — add second UserPromptSubmit entry for remind.py
core/phases: `scripts/klc`, src=scripts/klc:90 — add `remind` to LIFECYCLE_CMDS dispatch or add a separate handler; [!ASSUMPTION if-false=scope-may-expand] may require a new `core/phases/remind.py` entry point mirroring gate.py's structure
core/skills/phase_completion: `core/skills/phase_completion.py`, src=core/skills/phase_completion.py:450 — `can_complete(ticket, phase_id)` is the existing public API consumed by `klc remind`; no changes needed here

## Estimate
complexity: 2
uncertainty: 1
risk: 0
manual: 0
total: 3

DISCOVERY_LITE_DONE
