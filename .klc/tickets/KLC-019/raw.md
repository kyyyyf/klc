---
ticket: KLC-019
kind_hint: bug
created: 2026-06-04T15:03:24Z
---
`config/profile.yml` is acting like two different contracts at once:

- `core/skills/detect_languages.py` treats `languages` as a valid optional override and merges it into auto-detected languages.
- `core/skills/validate_config.py` currently flags `languages` as an unknown key in `profile.yml`.
- `core/skills/profile-resolve.py` only resolves the active `profile` name and does not define `languages`, so the profile file is supposed to stay small and explicit.

This creates a config-level mismatch: a project can set `languages` and get the expected behavior at runtime, but `klc doctor` / config validation will complain about the same file. That makes the profile contract ambiguous and brittle.

What I need fixed:

1. Decide whether `languages` is officially part of `profile.yml` or should be removed entirely.
2. Make the validator, docs, and language detection code agree on the same contract.
3. Keep the active profile selection behavior unchanged: `profile: generic` / `profile: ue` (with default generic) still selects `profiles/<name>/manifest.yml`, and per-project `.klc/config/profile.yml` still overrides framework defaults.


Relevant files and current behavior:

- `config/profile.yml`: selects the active profile.
- `profiles/generic/manifest.yml` and `profiles/ue/manifest.yml`: define the profile-specific runtime behavior.
- `core/skills/detect_languages.py`: reads `config/profile.yml` and currently accepts `languages` as a manual override.
- `core/skills/validate_config.py`: schema validation for config files; this is where the mismatch shows up.
- `core/skills/profile-resolve.py`: resolves the active profile and its manifest fields.

Concrete expectation:

- If `languages` stays, it should be documented and validated as optional.
- If `languages` goes away, `detect_languages.py` should stop reading it and use only inventory/indexer signals.

Either choice is fine, but it must be consistent across code, validation, and docs.
