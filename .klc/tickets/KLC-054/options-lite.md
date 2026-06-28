## Approach options

- Option A: subprocess-git — wrap `git pull --rebase` and `git push` via `subprocess.run`; classify non-fast-forward by exit code + stderr pattern; retry loop in pure Python. Low dependency footprint; easily unit-tested against a local bare repo with `git init --bare`.
- Option B: GitPython — use the `git` library's `Repo` abstraction for push/fetch/rebase; richer object model but adds an external dependency (`pip install gitpython`) and requires the library to be available in all klc execution environments.
- Option C: pygit2/libgit2 — low-level C bindings; maximum control over CAS semantics but very heavy dependency for plumbing-only work.

Picked: Option A — subprocess-git is dependency-free, already consistent with how the rest of the klc codebase shells out to git (no gitpython anywhere in `core/`), and the retry/conflict-classification logic maps cleanly to exit codes and stderr strings without any library overhead.
