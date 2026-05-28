# Review sub-agent job: security

Prompt file: profiles/ue/agents/review/security.md
Inputs:
- diff:              /mnt/d/a_work/.klc/reports/pending-2026-05-28-10-17/diff.patch
- spec:              /mnt/d/a_work/.klc/tickets/KLC-001/spec.md
- claude_md_context: /mnt/d/a_work/.klc/reports/pending-2026-05-28-10-17/claude-md-context.md
- allowlist:         /mnt/d/a_work/klc/config/reviewer-allowlist.seed.yml
- severity_rubric:   /mnt/d/a_work/klc/config/severity-rubric.md
- rule_catalog:      /mnt/d/a_work/.klc/reports/pending-2026-05-28-10-17/rule_catalog-security.txt

Before emitting any finding, read the allowlist. If a finding matches
an entry whose `reviewer` is "security" or "*", downgrade to INFO and append
`(allowlisted: <reason>)` to the title, per the prompt's Hard rules.

Write TWO outputs (Phase 1.2):
1. findings.json to /mnt/d/a_work/.klc/reports/partials-2026-05-28-10-17/security/findings.json
2. Markdown partial to /mnt/d/a_work/.klc/reports/partials-2026-05-28-10-17/security.partial.md

Required trailer (last line of the markdown partial):
  ISSUES_TOTAL=<n> ISSUES_BLOCKING=<n>
