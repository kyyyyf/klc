---
name: klc-ship
description: Ack + next in one step. Use when the user wants to acknowledge the current phase and advance in one step.
argument-hint: <TICKET-ID> [options]
allowed-tools: Bash
---

# /klc:ship — Ack + next in one step

Run `klc ship $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.
