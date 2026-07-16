---
ticket: KLC-061
kind_hint: tech
created: 2026-07-16T08:56:51Z
---
Wrap forward/holder verbs (ship, steal, abort, jump, jira) in state_tx so feature-on multi-user gets CAS-push + holder-auth + deferred-Jira like intake/ack/next. Today ship advances the phase and fires Jira immediately but never CAS-pushes (rides a later verb's push); steal mutates meta.holder locally without pull/push -> remote shows old holder, others stay blocked. Sources: codex P1 (steal.py:87-91) + fresh-A MEDIUM (ship.py:85-92). Route ship through ack.run/next.run (already wrapped) rather than calling apply_ack/advance_to_next directly; wrap steal's holder mutation in state_tx.
