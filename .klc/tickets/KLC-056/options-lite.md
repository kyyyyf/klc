## Approach options
- Option A: Inline holder in lifecycle.py — add `acquire_holder`/`release_holder` directly to `lifecycle.py` alongside `read_meta`/`write_meta`; trade-off: zero new files, but already-large lifecycle module grows further and KLC-057 wiring becomes harder to isolate.
- Option B: Standalone holder.py skill — new `core/skills/holder.py` that calls `lifecycle.read_meta`/`write_meta`; keeps phase-holder logic self-contained, importable by KLC-057 without touching lifecycle internals, easy to test in isolation.
- Option C: Holder as a subclass/mixin of meta — holder fields managed as a frozen dataclass stored inside meta.json; adds type safety but over-engineers a two-field struct that mutates in-place.

Picked: Option B — standalone `holder.py` imports `read_meta`/`write_meta` from lifecycle, is independently testable, and gives KLC-057 a clean single-import surface without risking blast-radius on lifecycle.
