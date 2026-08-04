---
name: klc-ack
description: Confirm phase work is done (optionally with --pick N or --auto for gate-policy). Use when the user wants to confirm/approve that the current phase work is done, optionally picking a gate option.
argument-hint: <TICKET-ID> [options]
allowed-tools: Bash
---

# /klc:ack — Confirm phase work is done (optionally with --pick N or --auto for gate-policy)

Run `klc ack $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass the ticket key and any options straight through; surface
the CLI's phase/gate output, including any advisory or blocking lines, to the user.
