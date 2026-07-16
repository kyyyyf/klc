# Branch-first development → MR/PR → two remote mains (GitHub + GitLab)

This repo has **two** remotes that must both end up with an identical `main`:

- `gh`  → GitHub  (`github.com/kyyyyf/klc`)
- `origin` → GitLab (`gitlab.example.com/developer/klc`)

## The problem this solves

If you merge the **GitLab MR** and the **GitHub PR** *independently*, each forge
creates its **own merge commit** — same file content, different SHA. The two
`main`s then diverge, and the next push is rejected (non-fast-forward). We hit
this repeatedly (KLC-052, r4-hardening) and had to reconcile with a manual merge.

**Rule: a change is merged on ONE forge only; the other main is fast-forwarded
to match. Never click "merge" on both.**

## The workflow (per ticket / change)

1. **Branch** off the latest `main`:
   `git checkout main && git pull <canonical> && git checkout -b feature/klc-0NN-<slug>`
2. **Develop** on the branch (TDD, commits).
3. **Push the branch to BOTH remotes** so both forges can show it:
   `git push -u gh feature/klc-0NN-<slug> && git push origin feature/klc-0NN-<slug>`
4. **Open MR (GitLab) + PR (GitHub)** from that branch — for review/CI/visibility
   on both forges.
5. **Merge on the canonical forge ONLY** (pick one and stick to it — see below).
   That advances `<canonical>/main` via the forge's merge commit.
6. **Mirror `main` to the other remote** (fast-forward, no second merge commit):
   ```
   git fetch <canonical>
   git checkout main && git merge --ff-only <canonical>/main
   git push <other> main            # fast-forward; both mains now identical SHA
   ```
   The other forge's PR/MR then shows as merged (its branch commits are in `main`)
   or is closed manually — do NOT click merge on it.
7. Delete the feature branch on both remotes when done.

## Canonical forge — **GitHub `gh`** (decided 2026-07-16)

The merge point for every change is **GitHub `gh`**: merge the **PR** there.
GitLab `origin/main` is then always a `--ff-only` mirror of `gh/main`. The
invariant is "exactly one forge merges (gh), the other (origin) is `--ff-only`
mirrored." Never click merge on the GitLab MR — it exists for review/CI only.

## One-liner mirror helper

After merging the PR on GitHub (`gh`):
```
CANON=gh OTHER=origin; \
git fetch "$CANON" && git checkout main && git merge --ff-only "$CANON"/main && git push "$OTHER" main
```
If `--ff-only` refuses, the mains already diverged (someone merged on both) —
reconcile once with `git merge <other>/main` (identical trees → clean), push
both, and resume the discipline.

## Bookkeeping vs code

Pure `.klc/` lifecycle bookkeeping (phase acks, retrospectives) that is not part
of a reviewable code change may continue to be committed on `main` and pushed to
both remotes directly (fast-forward) — it carries no diff worth an MR/PR and
stays consistent as long as it is only ever pushed, never forge-merged.

## Why not merge locally + push both?

That works (and is what we did for the epic) and keeps mains consistent, but it
bypasses forge review/CI. Branch-first + single-forge-merge + mirror keeps the
MR/PR review trail **and** identical mains.
