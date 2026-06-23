# KLC project — Claude Code instructions

## Starting a ticket

Before any implementation work:

1. Switch to main, pull all remotes, and bring main up to date with the most
   recent upstream commits across all configured remotes.
2. Create a feature branch: `git checkout -b feature/<branch-name>`.
   Never work on main directly.

## Mandatory: external code review subagent before review-report

When implementing a KLC ticket and writing the review-report, **always** launch
a fresh (non-fork) code-reviewer subagent before writing `review-report.md`.

**Why**: internal review suffers from confirmation bias — the implementer knows
the intent and validates against ACs as written, not against the full codebase.
A fresh subagent catches cross-file gaps (e.g. a file was omitted from scope)
and intra-file contradictions introduced during build. KLC-035 through KLC-037
all had Codex findings that internal review missed for exactly this reason.

**How**:

```
Agent({
  subagent_type: "code-reviewer",   # fresh, no conversation context
  prompt: """
    Review the changes on branch <branch-name> for ticket <KEY>.
    Spec ACs: <paste from spec.md>
    Changed files: <git diff --name-only main..HEAD>

    Read each changed file in full. Check:
    1. Every AC is satisfied in code/prompts/tests.
    2. No related file was missed (e.g. if design.md got a rule, do other
       agent prompts for the same task also need it?).
    3. No intra-file contradictions introduced by the new additions.
    4. Tests cover the new behaviour (not just happy-path).

    Return: findings (severity HIGH/MEDIUM/LOW + description + suggested fix).
    Return empty list if none.
  """
})
```

Wait for the result before writing `review-report.md`. Assess each finding
(fix / won't fix + reason) and document the assessment in the report.

**Do not skip this step even for small or "obvious" changes.**

## Pushing

After implementation, push the feature branch to all configured remotes.
Before pushing, rebase onto the latest upstream main to avoid conflicts.

## Other reminders

- Always use `PROJECT_ROOT=/home/ek/projects/klc`.
- Scope expansion at `ack`: update `meta.json:affected_modules` rather than fighting it.
