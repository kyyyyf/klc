---
name: klc-jump
description: Jump the ticket to a specific phase. Use when the user wants to jump a klc ticket to a specific phase.
argument-hint: <TICKET-ID> [options]
allowed-tools: Bash
---

# /klc:jump — Jump the ticket to a specific phase

Run `klc jump $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.
