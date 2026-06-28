# Agent prompt — KLC-057 · build:work · step-1

Ticket: **KLC-057** · track: **M** · kind: **tech**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

- Make the multi-user state-repo behaviour **unobtrusive**: a user runs the
  existing verbs (`klc intake`, `klc ack`, `klc next`) exactly as today and
  never learns that `.klc/` is a clone of a shared git "state repo". All
  pull/push/holder mechanics live **inside** the verbs.
- Enforce **key uniqueness** at intake across collaborators using git-CAS
  push (non-fast-forward rejection) as the coordination primitive — a key
  already created by someone else fails with a clear "already taken" message,
  with no local ticket dir left behind.
- Establish the **holder lifecycle** on the work verbs: `intake` acquires the
  holder for the new ticket's first phase; `ack` releases the holder on a
  successful forward transition; `next` / start-of-work first-grabs the free
  phase it is about to enter.
- Keep every change **fail-safe and backward-compatible**: when the state-repo
  feature is not configured (single-user / no `klc-state` remote), the verbs
  behave exactly as they do today (no pull, no push, no holder).

## Acceptance Criteria

1. AC-1 (intake uniqueness — happy path): Given the state-repo feature is
   configured and key `K` is free, when a user runs `klc intake K "..."`, then
   the verb performs `pull_rebase` first, creates the ticket locally, and the
   creation is persisted to the state repo via a CAS push that succeeds;
   `INTAKE_OK K` is printed and exit code is 0.

2. AC-2 (intake uniqueness — taken key): Given key `K` was already created by
   another collaborator (their meta for `K` is in the state repo), when a user
   runs `klc intake K "..."`, then the CAS push for `K` is rejected
   (non-fast-forward), the command exits non-zero with a message that names `K`
   as **already taken**, and **no partial local artifacts for `K` remain**
   (no `meta.json`, no orphan entry appended to the global tickets index).

3. AC-3 (intake acquires holder): Given AC-1 succeeded, when intake completes,
   then the new ticket's first phase records the current user (from
   `identity.current`, i.e. `git config user.email`) as its **holder** in
   `meta.json`, and that holder assignment is included in the same CAS-pushed
   state.

4. AC-4 (ack releases holder on forward transition): Given the current user
   holds phase `P` of ticket `K` and `klc ack K` advances to the next phase,
   when ack completes, then the verb has run `pull_rebase` → existing
   validation/gate-policy → phase advance → **release of the holder for `P`** →
   CAS push, and the released holder is reflected in `meta.json`.

5. AC-5 (ack ordering & atomicity): Given a successful `klc ack`, then the
   release-holder step happens **after** the phase advance and **before** the
   push, so a single CAS push carries both the advance and the release; if the
   CAS push is rejected, the command exits non-zero and reports a concurrent
   update without having advanced the *remote* phase.

6. AC-6 (next / start-of-work first-grab): Given ticket `K` is at `<P>:ack`
   with phase `P+1` free (no holder), when a user runs `klc next K`, then after
   `pull_rebase` the verb advances to `<P+1>:work` and **first-grabs** `P+1` —
   the current user becomes its holder — and the grab is CAS-pushed. If `P+1` is
   already held by another user, the verb reports it as taken and does not steal
   it (stealing is KLC-058's concern, out of scope here).

7. AC-7 (hidden from the user): None of the three verbs print state-repo, clone,
   remote, or git-internals language on the success path; existing human-facing
   output (e.g. `INTAKE_OK`, `→ <state>`, prompt-card hints) is unchanged in
   shape. The only new user-visible text is on the *failure* paths (key already
   taken; phase held by someone else; concurrent update — retry).

8. AC-8 (feature-off backward compatibility): Given the state-repo feature is
   **not** configured (no `klc-state` remote / feature flag off), when any of
   the three verbs runs, then behaviour is byte-for-byte identical to today —
   no pull, no push, no holder fields written — and all existing intake/ack/next
   tests still pass.

9. AC-9 (per-ticket lock preserved): The new sync/holder logic runs **inside**
   the existing `acquire_lock(ticket)` critical section in `ack`/`next` (and an
   equivalent guard for `intake`), so local concurrent `next`/`ack` cannot
   interleave with the remote sync. src=core/phases/ack.py:64,
   core/phases/next.py:46 verified=2026-06-27

10. AC-10 (tests): Add integration tests under `tests/integration/` that cover:
    intake-taken-key rollback (AC-2), intake-acquires-holder (AC-3),
    ack-releases-holder ordering (AC-4/AC-5), next-first-grab and
    held-by-other (AC-6), and feature-off no-op (AC-8). The git-CAS layer is
    exercised through a local bare-repo fixture or a stubbed `state_sync` that
    simulates non-fast-forward rejection; tests must not require a network remote.

### Current step — step-1

**feature detector: state_feature.enabled()**

**Goal:** Add `core/skills/state_feature.py` whose `enabled()` returns True iff a
`klc-state` git remote exists in the klc dir, so every other step has one
authoritative no-op switch (D-004 / C-004 / AC-8).

**RED:** `tests/test_state_feature.py::test_enabled_false_without_klc_state_remote`
— fails because `state_feature` does not exist; asserts `enabled()` is False in a
repo with no `klc-state` remote.

**GREEN:** Implement `enabled()` running `git remote` in `klc_dir()` and checking
for a line equal to `klc-state`; return False on any git error (fail-safe off).

**Interfaces:**
```python
def enabled() -> bool: ...
```

**Expected:** `2 passed` (no-remote → False; klc-state remote present → True).

**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/test_state_feature.py -x -q`

**COMMIT:** `KLC-057 step-1: state_feature.enabled() detects klc-state remote`

**Affected:** `core/skills/state_feature.py` (new), `tests/test_state_feature.py` (new).

**Code sketch:**
```python
import subprocess
from _paths import klc_dir

def enabled() -> bool:
    try:
        r = subprocess.run(["git", "remote"], cwd=klc_dir(),
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return "klc-state" in r.stdout.split()
```

**Depends-on:** none

**Affected files**:


**Expected tests**:



### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.

### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/home/ek/projects/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-057 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-057/impl-plan.md`
- Full spec: `.klc/tickets/KLC-057/spec.md`
- Full test-plan: `.klc/tickets/KLC-057/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-057 step-1` and
run `klc step KLC-057 2` to get the next step's card,
or `klc ack KLC-057 --pick 1` if this was the last step.
