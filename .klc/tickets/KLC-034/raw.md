---
ticket: KLC-034
kind_hint: feature
created: 2026-06-22T14:33:34Z
---
Wire AskUserQuestion and live re-route signals into the discovery Socratic protocol (KLC-SP roadmap item 1.1 residuals, beyond shipped KLC-032). Three gaps remain after KLC-032: (1) the one-question-at-a-time rule is prose only — the AskUserQuestion tool is referenced nowhere in core/agents; wire it into discovery.md and discovery-lite.md so the agent asks exactly one question per tool call. (2) DISCOVERY_LITE_UPGRADE_M is emitted by discovery-lite.md but detected by no skill (a dead signal) — make phase_completion surface it as a re-route advisory like DISCOVERY_DECOMPOSE, pointing at klc retrack. (3) one-question-at-a-time is only phrase-asserted in the harness; add a behavioral judge() fixture that fails on a batched-questions prompt and passes on the wired prompt. Plus docs parity in docs/process.md, docs/roles.md, docs/process-artifacts.md.
