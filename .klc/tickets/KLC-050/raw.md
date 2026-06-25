---
ticket: KLC-050
kind_hint: tech
created: 2026-06-25T07:09:33Z
---
Gate hardening: close the four judgment-side weaknesses found in the quality review. Broaden the no-pre-judgment lint to catch contractions and paraphrases (don't flag, ignore this, treat as minor, downgrade it). Make recorded_pick reject verbatim placeholder picks like Picked angle-bracket placeholder or Picked TBD. Make the model-on-subagent guard reject (non-zero) a dispatch with no resolved model instead of only warning. Unify the two step-N parsers and delete or align the stale impl-plan jinja templates.
