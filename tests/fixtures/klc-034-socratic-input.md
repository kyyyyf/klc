# Raw ticket: add Redis caching to user session lookups

The team wants to speed up repeated user session lookups by caching them in Redis.
Multiple unknowns exist:

- Should we cache per-user ID or per-session token? These have different invalidation implications.
- What TTL is appropriate given our current session expiry policy (not yet confirmed)?
- Should the cache be invalidated on user role change, or only on explicit logout?
- Is there a Redis instance already available in the infra, or does one need to be provisioned?

The requester wants the simplest approach that doesn't break existing auth flows.
