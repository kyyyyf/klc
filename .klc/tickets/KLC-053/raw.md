---
ticket: KLC-053
kind_hint: unknown
created: 2026-06-27T07:22:34Z
---
State bootstrap (project-scoped, orphan branch): klc state init materializes the project's `klc-state` orphan branch as a git worktree at .klc/ in the SAME repo (creating the orphan branch if it does not exist yet on origin or locally); one-time per checkout; existing klc reads .klc/tickets unchanged. No separate state repo. .klc/ stays in main's .gitignore (it is a worktree of another branch). Usage clone does not materialize .klc/; work clone = clone + klc state init.
