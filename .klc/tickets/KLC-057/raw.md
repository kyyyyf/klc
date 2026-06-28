---
ticket: KLC-057
kind_hint: unknown
created: 2026-06-27T07:23:36Z
---
Wire sync+holder into intake/ack/next plus uniqueness: intake does pull then uniqueness via CAS-push then create then acquire_holder then push; ack does pull validate gate-policy advance release_holder push; next/start-work first-grab free phase; all hidden inside verbs, user does not know about klc-state
