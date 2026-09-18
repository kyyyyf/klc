## Provenance on claims

Every FACT/ASSUMPTION/DECISION carries `evidence=observed|read|assumed`. `observed` needs
a fenced command+output block next to it; `read` needs a resolving `src=<file>:<line>`;
`assumed` needs a non-empty `if-false=`.

A runtime-behaviour premise (layout, ordering, timing, a tool/library's real behaviour)
must be `observed`, probed now, during design — not deferred to the manual phase, never
promoted from a citation alone. An item predating this attribute carries no `evidence=`.
