---
ticket: KLC-019
kind: bug
authority: human
track: S
risk_tags: []
---

## Goals

Make `profile.yml` contract unambiguous: the file selects only the active
profile name. Remove the undocumented `languages` override from
`detect_languages.py` and confirm the validator, code, and docs all agree.

## Acceptance Criteria

- [ ] AC-1: `detect_languages.py` no longer reads `languages` from `profile.yml`.
  Language detection uses only `inventory.json` threshold logic.
- [ ] AC-2: `validate_config.py` schema for `profile.yml` stays as `{"profile"}` —
  no change needed (it was already correct; test confirms it).
- [ ] AC-3: `klc doctor` passes with no warnings on the current `config/profile.yml`.
- [ ] AC-4: `detect_languages.py` docstring and module comment updated to remove
  references to `profile.yml` language override.
- [ ] AC-5: `docs/process.md` (or relevant doc) updated — no mention of `languages`
  in `profile.yml` as a valid key.

## Affected

- `core/skills/detect_languages.py`: remove Step 2 (lines ~84-95, `profile.get("languages")`)
  and update docstring — src=core/skills/detect_languages.py:84-95
- `core/skills/validate_config.py`: no code change; add comment confirming
  `profile` is the only valid key — src=core/skills/validate_config.py

## Estimate

complexity: 1
uncertainty: 0
risk: 0
manual: 0
total: 1
