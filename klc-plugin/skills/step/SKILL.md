---
name: klc-step
description: Show or advance the current build step. Use when the user wants to show or advance the current build step of a klc ticket.
argument-hint: <TICKET-ID> [options]
allowed-tools: Bash
---

# /klc:step — Show or advance the current build step

Run `klc step $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.
