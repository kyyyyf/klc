---
name: klc-next
description: Advance the ticket to the next work phase. Use when the user wants to move a klc ticket forward to its next phase.
argument-hint: <TICKET-ID> [options]
allowed-tools: Bash
---

# /klc:next — Advance the ticket to the next work phase

Run `klc next $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.
