---
ticket: KLC-019
phase: build
authority: agent
---

# KLC-019 build log

## Step 1 — remove languages override from detect_languages.py

**Outcome**: green

- Removed Step 2 (profile.yml languages read) from `detect()`
- Updated module docstring and function docstring
- No `profile.get("languages")` call remains in runtime code
- Removed unused `import yaml` and `klc_config_dir` path read

## Step 2 — clarify validate_config.py schema comment

**Outcome**: green

- Added inline comment to profile.yml schema explaining `languages` is
  intentionally excluded and why

**Verification**: doctor OK, smoke OK, e2e all tracks pass.
AC-2 confirmed: synthetic profile.yml with `languages` key → warning.
