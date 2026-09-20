"""tdd_order.py — Red-before-green commit ordering verifier (KLC-039).

For each build step, asserts that a test-touching commit precedes the
first implementation commit in the step's git history.  Never raises on
a missing or shallow repo — degrades to a clear sanction reason instead.

KLC-109: the test-path predicate is no longer a private ``tests/``-segment
regex — it delegates to the shared ``test_conventions`` module (D-103),
recognising filename-adjacent layouts (``Foo.test.tsx``, ``foo_test.go``,
``FooTest.java``, ``foo_spec.rb``, ...) and honouring the active profile's
extended table (D-203) — the gate is NOT exempted from a profile's declared
layout (see ``classify``'s docstring).

KLC-109 review-fix round 2 (D-109-10, code-review HIGH #2): ``classify``'s
sibling-existence probe (test_conventions's ``exists=`` seam) is backed by
a git tree (``git ls-tree -r --name-only <sha>``, cached once per commit),
never today's working-tree checkout — a HARD gate that
``phase_completion.can_complete_build``/``remind.py`` re-verify on every
prompt must answer the same way for an already-acked commit forever,
regardless of what an unrelated LATER commit does to the sibling file.

KLC-109 review-fix round 4 (D-109-12, supersedes D-109-10, code-review HIGH
round 3): D-109-10's fix anchored EVERY commit in a step to the STEP'S OWN
LAST commit's tree — stable against a LATER, unrelated commit outside the
step, but unstable against the step's OWN, ordinary in-progress state: a
step whose only landed commit is its RED test (the GREEN commit not yet
committed) has, as its own tip, a tree with no confirmed sibling yet, so it
was misclassified ``impl`` and falsely sanctioned; and a later, same-step
fix-up that removes the production sibling could retroactively flip an
already-passing step. ``classify`` now looks at NOTHING but the ONE commit
being classified and its immediate PARENT (first-parent for a merge): the
sibling-existence probe (``exists=``) is confirmed against the UNION of the
commit's own tree and its parent's tree, and a NEW ``added=`` predicate
(test_conventions's D-109-12 seam) tells whether the classified path itself
is ABSENT from the parent tree — i.e. added by this very commit. A
basename-shaped path that is freshly ADDED needs no sibling confirmed at
all (an honest RED commit never has one yet); a path that PRE-EXISTS (was
already in the parent tree) still needs a confirmed sibling, so a bare
production edit to an established file (``core/skills/test_map.py``) stays
sanctioned. Every input to this decision — a commit's own tree, its
parent's tree, whether a path is in the parent's tree — is an IMMUTABLE
property of the two commits' git objects, so temporal stability follows
directly from git's own immutability: no later commit, in this step or
any other, can ever change what the parent tree of an EARLIER, already-made
commit was.
"""
from __future__ import annotations

import functools
import subprocess
import sys
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_file_dir))
import test_conventions as _tc  # noqa: E402


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], repo: Path | None = None) -> str:
    """Run git and return stdout; return empty string on any error."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(repo) if repo else None,
            timeout=30,
        )
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


@functools.lru_cache(maxsize=256)
def _commit_tree_members(commit_sha: str, repo_str: str) -> frozenset[str]:
    """The set of paths in *commit_sha*'s OWN git tree (``git ls-tree -r
    --name-only <sha>``), cached per (sha, repo) so repeated ``classify``
    calls for the same commit (e.g. across every step ``can_complete_build``
    re-verifies) run the ls-tree once.

    HIGH #2: this is what makes ``classify``'s sibling-existence probe a pure
    function of the commit being classified, never of today's working-tree
    checkout — an already-acked step's verdict cannot flip just because a
    LATER, unrelated commit deleted the sibling file. Returns an empty
    frozenset on any git failure (never raises); an empty set degrades to
    the same conservative "no sibling confirmed" answer as any other
    unavailable ``exists=`` source."""
    repo = Path(repo_str) if repo_str else None
    out = _git(["ls-tree", "-r", "--name-only", commit_sha], repo)
    return frozenset(line.strip() for line in out.splitlines() if line.strip())


@functools.lru_cache(maxsize=256)
def _commit_parent_sha(commit_sha: str, repo_str: str) -> str:
    """The first-parent SHA of *commit_sha* (``git rev-parse <sha>^``, which
    is always the FIRST parent, including for a merge commit), or ``""`` for
    a root commit or on any git failure. An empty string is a safe input to
    ``_commit_tree_members`` — ``git ls-tree`` on an empty ref also fails and
    degrades to an empty frozenset, i.e. "no parent tree", exactly the right
    answer for a root commit (D-109-12: every path in a root commit is, by
    definition, ADDED relative to its — nonexistent — parent)."""
    repo = Path(repo_str) if repo_str else None
    return _git(["rev-parse", f"{commit_sha}^"], repo).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def step_commits(
    ticket: str,
    step: int,
    repo: Path | None = None,
) -> list[dict]:
    """Return commits for *ticket* step-*step* in chronological order (oldest first).

    Each entry is ``{"sha": str, "subject": str}``.  Returns ``[]`` when git
    is unavailable or no matching commits exist.

    Post-filters git output so that step-1 does not accidentally include
    commits for step-10, step-11, etc.
    """
    import re as _re
    pattern = f"{ticket} step-{step}"
    out = _git(["log", "--format=%H\t%s", "--reverse", f"--grep={pattern}"], repo)
    # Require the step number to not be followed by another digit.
    exact_re = _re.compile(rf"{_re.escape(ticket)}\s+step-{step}(?!\d)")
    commits = []
    for line in out.splitlines():
        line = line.strip()
        if "\t" in line:
            sha, subject = line.split("\t", 1)
            sha = sha.strip()
            subject = subject.strip()
            if exact_re.search(subject):
                commits.append({"sha": sha, "subject": subject})
    return commits


def classify(commit_sha: str, repo: Path | None = None) -> str:
    """Classify a commit by the paths it touches.

    Returns one of:
    - ``"test"``  — only test files changed (by filename convention, D-103)
    - ``"impl"``  — only non-test files changed (or unknown)
    - ``"mixed"`` — both test and non-test files changed

    D-203: the gate is NOT exempt from the profile table. A layout a profile
    declares must be a test here too, or e.g. a UE `FooSpec.cpp` is a test for
    `test_map` and an implementation commit for the ack gate — the exact
    split-brain KLC-109 exists to remove. `active_table()` never raises and
    degrades to the built-in table, which is what C-001 requires.

    KLC-109 review-fix round 4 (D-109-12, supersedes D-109-10, AC-6, code-review
    HIGH round 3): classification is PER COMMIT, against that commit's own two
    IMMUTABLE trees — never a step's tip, never today's working-tree checkout:

    - `exists=` (the sibling-existence probe) is backed by the UNION of the
      commit's OWN tree and its PARENT's tree (`_commit_tree_members`, cached
      per sha; `_commit_parent_sha` resolves the first parent, `""` for a
      root commit or merge-parent lookup failure, which degrades to an empty
      parent tree — never raises).
    - `added=` tells whether the path being classified is ABSENT from the
      parent tree, i.e. newly introduced by this commit. A basename-shaped
      match that is freshly ADDED is a test with no sibling required yet (an
      honest RED commit is added before its GREEN sibling exists, by
      construction); a PRE-EXISTING path still needs a confirmed sibling, so
      a bare edit to an established file (`core/skills/test_map.py`) stays
      sanctioned.

    Both trees belong to commits that, once made, never change — so this
    answer is stable forever for a given `commit_sha`, regardless of what any
    OTHER commit (earlier, later, same step or a different one) does.
    """
    out = _git(["show", "--name-only", "--format=", commit_sha], repo)
    files = [f.strip() for f in out.splitlines() if f.strip()]
    if not files:
        return "impl"
    table = _tc.active_table()
    repo_str = str(repo) if repo else ""
    own_tree = _commit_tree_members(commit_sha, repo_str)
    parent_sha = _commit_parent_sha(commit_sha, repo_str)
    parent_tree = _commit_tree_members(parent_sha, repo_str)
    exists_set = own_tree | parent_tree
    added = lambda p: p not in parent_tree  # noqa: E731 — path absent from the parent tree
    has_test = any(_tc.is_test_path(f, table=table, exists=exists_set.__contains__,
                                    added=added) for f in files)
    has_impl = any(not _tc.is_test_path(f, table=table, exists=exists_set.__contains__,
                                        added=added) for f in files)
    if has_test and has_impl:
        return "mixed"          # 'mixed' stays non-test for verify_step, so a
    return "test" if has_test else "impl"   # wider predicate cannot weaken the gate


def verify_step(
    ticket: str,
    step: int,
    repo: Path | None = None,
) -> tuple[bool, str]:
    """Verify red-before-green commit ordering for a build step.

    Returns ``(ok, reason)`` where:
    - ``ok=True``  — a test-only commit precedes the first impl/mixed commit.
    - ``ok=False`` — ordering violated, or no commits could be attributed.

    Pass *repo=None* to search git history in the current working directory.
    Never raises; always degrades to ``ok=False`` with a descriptive reason.
    """
    commits = step_commits(ticket, step, repo)
    if not commits:
        return (
            False,
            f"{ticket} step-{step}: no commits found matching '{ticket} step-{step}' "
            "in git message — cannot verify TDD order; "
            "ensure commits carry the step key in their commit message",
        )

    # D-109-12: every commit is classified against its OWN two immutable
    # trees (see classify's docstring) — never a step tip, never today's
    # live working tree, so temporal stability follows from tree immutability
    # rather than from anchoring to a moving "last commit so far".
    classified = [(c, classify(c["sha"], repo)) for c in commits]

    first_test_idx = next(
        (i for i, (_, cls) in enumerate(classified) if cls == "test"), None
    )
    first_nontest_idx = next(
        (i for i, (_, cls) in enumerate(classified) if cls in ("impl", "mixed")), None
    )

    if first_nontest_idx is None:
        # Only test commits — no impl yet; ordering is fine.
        return True, ""

    if first_test_idx is None:
        sha = classified[first_nontest_idx][0]["sha"][:8]
        return (
            False,
            f"{ticket} step-{step}: implementation commit ({sha}) found with no "
            "preceding failing-test commit — red-before-green ordering violated",
        )

    if first_test_idx < first_nontest_idx:
        return True, ""

    sha = classified[first_nontest_idx][0]["sha"][:8]
    return (
        False,
        f"{ticket} step-{step}: implementation commit ({sha}) precedes test commit — "
        "red-before-green ordering violated; commit the failing test first",
    )
