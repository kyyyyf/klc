## Completion signal (orchestrator)

End with ONE fenced JSON block as the LAST output block:

```json
{"phase":"x","signal":"done","artifacts":["a"],"blocking_questions":[],"next_action":"ack"}
```

`phase`=agent minus klc-; `signal`=`done`|`blocked`|`failed`;
`artifacts`=paths; `blocking_questions`=`[]`|list;
`next_action`=`ack`|`clarify`|`stop`.
`"tokens":{"in":N,"out":N}` ONLY if your host shows you your usage;
absent is normal, klc estimates from the card.
