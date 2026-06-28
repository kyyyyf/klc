## Approach options
- Option A: In-process heartbeat via explicit caller call — `heartbeat_holder(ticket)` is a pure function in `lifecycle.py`; the caller (e.g., a long-running build loop) must call it periodically. Simple, no background threads, no new dependencies; relies on the agent/script to call it.
- Option B: Background thread auto-heartbeat — launch a daemon thread inside `lifecycle.py` that fires every N seconds. Removes caller burden but introduces threading complexity and Python daemon-thread caveats (abrupt exit on crash, test isolation issues).

Picked: Option A — pure function with explicit caller invocation; simpler to test, no threading risk, consistent with the rest of the codebase's synchronous-over-files design.
