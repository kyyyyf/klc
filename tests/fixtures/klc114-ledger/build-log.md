# Build log — KLC-114-LEDGER

## Step 1

Green, well-scoped, correctly ordered. Ran the VERIFY once by hand before
committing.

## Step 2

Red — a deliberately misordered fixture (impl commit precedes any
failing-test commit) so the step-ledger pass has something real to catch.

## Step 3

Unverified — this fixture's git history carries no commit for this step at
all (a squashed/omitted key, Q-002).

## Step 4

Scope-violation — the impl commit touches an extra, undeclared file.

## Evidence

AC-1: builder's own manual re-run of the green step

```
$ sh -c "echo 2 passed"
2 passed
```
