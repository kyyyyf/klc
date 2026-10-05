---
name: klc-fix
description: Correct a ticket's meta field with an audited record. Use when the user wants to change a klc ticket's track, modules, risk tags, kind, epic or blockers.
argument-hint: <TICKET-ID> [options]
disable-model-invocation: true
allowed-tools: Bash
---

# /klc:fix — Correct a ticket's meta field with an audited record

Run `klc fix $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.
