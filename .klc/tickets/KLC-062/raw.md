---
ticket: KLC-062
kind_hint: bug
created: 2026-07-16T08:56:51Z
---
klc remind must be truly read-only. can_complete_discovery -> _sync_risk_tags rewrites meta.json on EVERY UserPromptSubmit for a held discovery:work ticket (per-prompt git-dirty churn) -- remind is in NO_DRAIN_CMDS precisely because it is assumed read-only. Fix: use a read-only completion probe (or make can_complete/_sync_risk_tags side-effect-free and move risk_tags persistence to ack). Also: legacy-phase migration writes through lifecycle.read_meta in remind.py:101 and status.py:41 despite status claiming read-only (board.py avoids it via raw json.loads). Source: fresh-C MEDIUM+LOW. Add a discovery:work-completable test asserting meta.json byte-identical after klc remind.
