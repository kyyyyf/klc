---
name: klc-abort
description: Cancel current work and return to the previous ack state. Use when the user wants to cancel the current klc work and return to the previous ack state.
argument-hint: <TICKET-ID> [options]
allowed-tools: Bash
---

# /klc:abort — Cancel current work and return to the previous ack state

Run `klc abort $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.
