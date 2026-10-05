---
name: klc-back
description: Return the ticket to an earlier phase with a reason. Use when the user wants to redo an earlier phase of a klc ticket.
argument-hint: <TICKET-ID> [options]
allowed-tools: Bash
---

# /klc:back — Return the ticket to an earlier phase with a reason

Run `klc back $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.
