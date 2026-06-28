## Approach options
- Option A: New `core/phases/state.py` + dispatcher entry — add `klc state <sub>` as a first-class lifecycle command dispatched via `_run_phase("state", rest)`, with `state.py` implementing `klc state init` using `git checkout --orphan klc-state` (when absent) + `git worktree add .klc klc-state` in the current project repo.
- Option B: Inline in `scripts/klc` dispatcher — implement state init logic directly inside the `_dispatch` function with no new phase file, keeping the change entirely in one file at the cost of coupling init logic to the dispatcher.

Picked: Option A — matches the existing pattern (`install.py`, `setup.py`); keeps the dispatcher thin and the init logic independently testable.
