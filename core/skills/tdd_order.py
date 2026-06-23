"""tdd_order.py — Red-before-green commit ordering verifier (KLC-039).

For each build step, asserts that a test-touching commit precedes the
first implementation commit in the step's git history.  Never raises on
a missing or shallow repo — degrades to a clear sanction reason instead.
"""
from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath


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


def _is_test_path(path: str) -> bool:
    """True when path lives inside the tests/ directory."""
    parts = PurePosixPath(path).parts
    return bool(parts) and parts[0] == "tests"


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
    """
    pattern = f"{ticket} step-{step}"
    out = _git(["log", "--format=%H\t%s", "--reverse", f"--grep={pattern}"], repo)
    commits = []
    for line in out.splitlines():
        line = line.strip()
        if "\t" in line:
            sha, subject = line.split("\t", 1)
            commits.append({"sha": sha.strip(), "subject": subject.strip()})
    return commits


def classify(commit_sha: str, repo: Path | None = None) -> str:
    """Classify a commit by the paths it touches.

    Returns one of:
    - ``"test"``  — only ``tests/`` files changed
    - ``"impl"``  — only non-test files changed (or unknown)
    - ``"mixed"`` — both test and non-test files changed
    """
    out = _git(["show", "--name-only", "--format=", commit_sha], repo)
    files = [f.strip() for f in out.splitlines() if f.strip()]
    if not files:
        return "impl"
    has_test = any(_is_test_path(f) for f in files)
    has_impl = any(not _is_test_path(f) for f in files)
    if has_test and has_impl:
        return "mixed"
    return "test" if has_test else "impl"


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
            f"{ticket} step-{step}: no commits found matching subject pattern "
            f"'{ticket} step-{step}' — cannot verify TDD order; "
            "ensure commits carry the step subject per the impl-plan contract",
        )

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
