---
name: klc-status
description: Show current phase and track for a ticket. Use when the user wants to check what phase or track a klc ticket is in.
argument-hint: <TICKET-ID> [options]
allowed-tools: Bash
---

# /klc:status — Show current phase and track for a ticket

Run `klc status $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.
