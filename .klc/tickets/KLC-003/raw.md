---
ticket: KLC-003
kind_hint: feature
created: 2026-05-28T10:48:26Z
---
# KLC-003 — GitLab/GitHub publish adapters for review results

## Context

Phase 3b: automate publishing of review-report.md results directly to GitLab MR / GitHub PR.

Currently `review.py` generates reports locally but doesn't publish them to the MR/PR. Users must manually read the report and update the MR.

## Problem

Manual workflow for review results:
1. Run `review.py --diff <branch> --spec <spec>`
2. Read `review-report.md` locally
3. Manually add labels to MR/PR
4. Manually add comments for findings
5. Manually update CI status

This breaks automation and slows down the review → merge cycle.

## Proposed solution

Add publish adapters for GitLab and GitHub:

**GitLab adapter** (`core/skills/publish_gitlab.py`):
- Set MR labels based on verdict (APPROVED / CHANGES REQUESTED)
- Post inline comments for findings (file:line → MR discussion thread)
- Update commit status for CI integration

**GitHub adapter** (`core/skills/publish_github.py`):
- Set PR labels based on verdict
- Post review comments for findings
- Update check runs status

**Integration point**: `review.py` calls adapters after generating report, controlled by env vars:
- `GITLAB_TOKEN` + `GITLAB_PROJECT_ID` + `GITLAB_MR_IID` → publish to GitLab
- `GITHUB_TOKEN` + `GITHUB_REPO` + `GITHUB_PR` → publish to GitHub

## Acceptance criteria

- AC-1: Given review verdict APPROVED, GitLab MR gets label "review:approved"
- AC-2: Given review verdict CHANGES REQUESTED, GitLab MR gets label "review:changes-requested" + commit status "failed"
- AC-3: Given finding at file:line, GitLab MR gets discussion thread at that location with finding details
- AC-4: Same for GitHub (labels, review comments, check run status)
- AC-5: Adapters skip publishing if tokens not set (graceful fallback to local-only mode)

## Out of scope

- Webhook receivers (passive mode only - triggered by CI, not by MR events)
- Multi-finding aggregation (one comment per finding initially)
- Finding deduplication across review iterations (future enhancement)

## Estimate

- Complexity: 2 (API integration, error handling, auth)
- Uncertainty: 1 (APIs well-documented)
- Risk: 0 (local reports still work without adapters)
- Manual: 1 (test on real MR/PR)
- Total: 4
- Track: S

## Related

- Phase 1-3a: review.py generates structured findings
- PHASE3A_COMPLETE.md line 132: "Phase 3b — Publish adapters"
