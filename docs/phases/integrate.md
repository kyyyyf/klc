# Integrate phase

## Purpose
Merge feature branch to main. Resolve conflicts if needed.

## Inputs
- Feature branch with all commits
- Main branch (up-to-date)

## Outputs
- Merged commit on main
- `integrate.md` — merge notes

## Process
1. Fetch and rebase on main: `git fetch gl main && git rebase gl/main`
2. Resolve any merge conflicts
3. Push to remote: `git push gl HEAD:main`
4. Write integrate.md with merge details

## Completion criteria
- Feature branch merged to main
- No conflicts remaining
- integrate.md documents merge

## Ack options
- `--pick 1` (complete): Advance based on track
  - XS → learn:work
  - S/M/L → observe:work
- `--pick 2` (conflict): Human resolves conflict, retry

## Common pitfalls
- Not rebasing before push → fast-forward rejection
- Forgetting to update main before creating feature branch
- Force-pushing (violates GitLab policy)

## Example
S ticket: Rebase on main → no conflicts → push → approve → observe:work  
XS ticket: Rebase → push → approve → learn:work
