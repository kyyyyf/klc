# Two remotes: origin is the real history, gh is a clean public mirror

This repo has **two** remotes that play **different roles** — they are *not* two
peers holding an identical `main`:

- `origin` → GitLab (`gitlab.example.com/e_konchikov/klc`) — the **real
  history** and the active development remote. All branches, MRs, review, and CI
  live here. It legitimately carries the operator's real identity and internal host
  references.
- `gh` → GitHub (`github.com/kyyyyf/klc`) — a **clean public mirror**. Since the
  2026-07-21 history scrub it is a *re-authored, content-scrubbed* lineage: every
  commit re-authored to the public GitHub identity, every internal reference
  removed. It is refreshed by force-push, and it takes **no pull requests**.

Because gh is re-authored and scrubbed, the two `main` branches hold the **same
content under different identity and history**. They are **intentionally
divergent** — not fast-forwards of each other. This is deliberate, so do not try to
reconcile them.

## Why the old model is gone

An earlier version of this doc said "merge on one forge, `--ff-only` mirror the
other, identical mains." That is **dead**. A `--ff-only` mirror is impossible once
gh is a re-authored lineage — the commits have different SHAs and different
authors by construction — and asserting identical mains would contradict the rule
that the public mirror must be scrubbed. See the constitution principles
`divergent-public-mirror` and `public-mirror-no-internal-refs`
(`docs/constitution.md`).

## The workflow (per ticket / change)

```text
1. Branch off the latest origin/main:
     git checkout main && git pull origin && git checkout -b feature/klc-0NN-<slug>
2. Develop on the branch (TDD, commits) — never on main directly (branch-first).
3. Push the branch to origin and open a Merge Request there:
     git push -u origin feature/klc-0NN-<slug>
4. Review + CI happen on the origin MR. Merge the MR on origin.
     origin/main now carries the real, un-scrubbed change.
5. Refresh the public mirror gh from origin/main via the scrub+re-author step
     (a filtered, re-authored force-push). NOT a merge, NOT a PR.
6. Delete the feature branch on origin when done.
```

## Publishing to gh (the scrub + re-author step)

The public mirror is produced by rewriting `origin/main` into a scrubbed,
re-authored lineage and force-pushing it to `gh/main`. The scrub must:

- **Re-author every commit** to the public GitHub identity (kyyyyf / a noreply
  address) — no internal email domain reaches gh.
- **Scrub internal references** from content — the internal git host and the
  corporate email domain must not appear anywhere in `gh/main`.

The denylist of internal tokens lives HERE, in the origin-side mirror tooling — it
is deliberately NOT committed into the constitution (`config/constitution.yml` /
`docs/constitution.md`), because a denylist committed onto the surface it guards
both ships those internal tokens to the public mirror and self-trips any gh-side
grep against its own denylist file. So `public-mirror-no-internal-refs` is a
`review` principle in the constitution, and this tooling is what enforces it.

Verify after publishing, using the tooling's denylist (the same tokens the scrub
`--replace-text` targets):

```text
git grep -iE "<internal-token-denylist>" gh/main                       # -> exit 1
git log gh/main --format="%ae%n%ce" | grep -iE "<internal-token-denylist>" # -> exit 1
```

Both must find nothing. A hit means the scrub missed something and the public
mirror is leaking — fix the scrub and re-push.

## Bookkeeping vs code

Pure `.klc/` lifecycle bookkeeping (phase acks, retrospectives) that is not part of
a reviewable code change may be committed on `origin/main` directly — it carries no
diff worth an MR. Everything with a code diff goes through a branch and an MR
(`branch-first`).
