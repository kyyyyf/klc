---
ticket: KLC-019
kind: bug
authority: agent
---

## Acceptance coverage

| # | AC | Test |
|---|----|----|
| 1.1 | AC-1: `languages` key removed | `detect_languages.detect()` with a `profile.yml` containing `languages: [python]` → key is ignored, result based on inventory only |
| 1.2 | AC-1: no `profile.get("languages")` call | `grep -n "languages" core/skills/detect_languages.py` → zero matches in runtime code |
| 2.1 | AC-2: validator still accepts only `profile` key | `validate_config.validate_file(Path("config/profile.yml"))` → no warnings |
| 2.2 | AC-2: validator rejects `languages` key | synthetic `profile.yml` with `languages: [python]` → warning "unknown keys: languages" |
| 3.1 | AC-3: `klc doctor` clean | `python3 core/phases/doctor.py` → DOCTOR_OK |
| 4.1 | AC-4: docstring updated | docstring no longer mentions `profile.yml` language override |
| 5.1 | AC-5: docs updated | `grep -r "languages" docs/` → no mentions of it as a `profile.yml` key |

## Edge cases

| # | Scenario | Expected |
|---|----------|----------|
| E-1 | `profile.yml` has only `profile: generic` | detect_languages works normally (inventory-based) |
| E-2 | no `profile.yml` at all | detect_languages still works (profile read is optional) |
| E-3 | existing `inventory.json` with python files | python detected via threshold, not via profile key |
