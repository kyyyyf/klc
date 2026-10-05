---
name: klc-doctor
description: Check install health, bootstrap a project or refresh the index. Use when the user wants to check klc health, set klc up in a project or refresh the code index.
argument-hint: [--install <root>] [--index]
disable-model-invocation: true
allowed-tools: Bash
---

# /klc:doctor — Check install health, bootstrap a project or refresh the index

Run `klc doctor $ARGUMENTS` via Bash and show the result verbatim. This is a thin
adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic
is reimplemented here). Pass any options straight through; surface the CLI's check, install and index output, including any advisory or blocking lines, to the user.
