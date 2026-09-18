## Completion signal (orchestrator)

End with ONE fenced JSON object as the LAST output block:

```json
{"phase":"design","signal":"done","artifacts":["design/options.md"],"blocking_questions":[],"next_action":"ack"}
```

`phase`: agent name minus `klc-`. `signal`: `done`|`blocked`|`failed`.
`artifacts`: paths written, relative to ticket dir. `blocking_questions`:
string[], `[]` if none. `next_action`: `ack`|`clarify`|`stop`. Optional:
`"tokens":{"in":N,"out":N}`
