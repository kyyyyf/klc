---
ticket: KLC-051
kind_hint: tech
created: 2026-06-25T08:24:14Z
---
Plan-quality gate: catch the specced-but-unwired class of defect at planning time. Add a mechanical API-existence check (extract module.attr references from impl-plan code sketches and flag any that name a real core/skills module whose attribute does not exist), wire it into the plan-completeness gate at design and discovery-lite ack, add a planning-prompt rule that every wired-behaviour AC maps to an end-to-end test at the public entry point and every gate AC maps to a negative plus fail-closed test, add a prompt-regression assert for that rule, extend the agent-side self-review to run the API-existence check before emitting, and document an adversarial completeness-audit as a standard build-ready prep step.
