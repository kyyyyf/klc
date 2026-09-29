"""Shared fixture helpers for the KLC-128 test suite.

Not collected by pytest (this module's name does not start with ``test_``).

Every KLC-128 test drives a REAL git fixture: a bare ``origin.git`` plus a
working clone under ``tmp_path``, real commits, real merges, real pushes —
never a monkeypatched ``_git``/``compare`` stub returning canned data (the
test-plan's own harness note, and the KLC-110 retro lesson, F-016).
``PROJECT_ROOT`` is pointed at the clone; its ``.klc/`` is a PLAIN directory
(never its own git worktree bound to ``klc-state``), so
``state_feature.enabled()`` reads False there and ``state_tx`` is a no-op
(design ``options.md`` F-206) — the ack flow runs entirely local, no push to
any state remote. This mirrors the fixture style of
``test_klc069_non_origin_remote.py`` / ``test_klc057_real_repo.py``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "core" / "phases")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ALICE_EMAIL = "alice@example.com"
ALICE_NAME = "Alice"

_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0"}


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={**_GIT_ENV, "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _git_rc(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={**_GIT_ENV, "HOME": str(cwd)},
    )


def _init_repo_config(repo: Path) -> None:
    _git(repo, "config", "user.email", ALICE_EMAIL)
    _git(repo, "config", "user.name", ALICE_NAME)
    _git(repo, "config", "commit.gpgsign", "false")


def _bare_and_clone(tmp_path: Path, *, initial_files: dict[str, str] | None = None
                    ) -> tuple[Path, Path]:
    """A bare ``origin.git`` (branch ``main``) plus a working clone, seeded with
    one initial commit on ``main`` (pushed). Returns ``(bare, clone)``."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)],
                   check=True, capture_output=True)

    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(bare), str(clone))
    _init_repo_config(clone)

    files = initial_files or {"README.md": "# fixture repo\n"}
    for rel, content in files.items():
        path = clone / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "initial commit")
    _git(clone, "push", "-u", "origin", "main")
    return bare, clone


def _branch_with_commits(clone: Path, ticket: str,
                         commits: list[tuple[str, str, str]],
                         *, base_branch: str = "main",
                         branch: str | None = None) -> str:
    """Check out ``feature/<ticket>`` (or an explicit *branch* override) off
    *base_branch* and apply real commits.

    *commits* is a list of ``(relative_path, content, message)``. A message
    may or may not contain the ticket key — some deliberately do not, to cover
    AC-2's keyless-squash case. KLC-129 (external review MEDIUM #1): *branch*
    lets a caller pin the REAL, lowercase `feature/klc-<n>-<slug>` shape this
    project's branches actually use (the default `feature/<TICKET>` is the
    canonical, uppercase, slug-less form every other KLC-128 test already
    relies on — left as the default so those 16 call sites are unaffected).
    Returns the branch name."""
    branch = branch or f"feature/{ticket}"
    _git(clone, "checkout", base_branch)
    _git(clone, "checkout", "-b", branch)
    for rel, content, message in commits:
        path = clone / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-m", message)
    return branch


def _seed_ticket(clone: Path, ticket: str, *, phase: str, track: str,
                 affected_modules: list[str] | None = None,
                 risk_tags: list[str] | None = None,
                 pre_merge_range: dict | None = None,
                 modules: list[dict] | None = None,
                 extra_meta: dict | None = None) -> Path:
    """Write ``.klc/tickets/<ticket>/meta.json``, ``.klc/index/modules.json``
    and the CURRENT phase's declared outputs into *clone*'s (untracked)
    ``.klc/`` directory — never ``spec.md``, ``test-plan.md`` or
    ``impl-plan.md`` (options F-206): the build ack's TDD-order / AC-coverage /
    step-verify arms all degrade cleanly to a no-op with nothing to check, and
    the generic completion check (review/manual) looks only at declared
    OUTPUTS, never at ``spec.md``.

    Returns the ticket directory path."""
    tdir = clone / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    pid = phase.split(":")[0]

    meta = {
        "ticket": ticket, "kind": "bug", "kind_source": "user",
        "phase": phase, "phase_history": [],
        "track": track, "route_hint": track, "route_confidence": "high",
        "affected_modules": affected_modules or [],
        "risk_tags": risk_tags or [],
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 1, "total": 4},
        "layer": "code", "budgets": {},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
        "owner": "test@example.com",
    }
    if pre_merge_range is not None:
        meta["pre_merge_range"] = pre_merge_range
    if extra_meta:
        meta.update(extra_meta)
    (tdir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    index_dir = clone / ".klc" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    modules_path = index_dir / "modules.json"
    if not modules_path.exists() or modules is not None:
        modules_path.write_text(
            json.dumps({"modules": modules or []}, indent=2) + "\n", encoding="utf-8")

    _write_phase_output(tdir, pid)
    return tdir


def _write_phase_output(tdir: Path, pid: str) -> None:
    """Write the declared-output artefact for phase *pid* so its generic
    completion check (or, for build, its AC-coverage/step-verify/TDD-order
    arms — all degrading cleanly with no spec.md/impl-plan.md present, F-206)
    passes."""
    if pid == "build":
        (tdir / "build-log.md").write_text(
            "# Build log\n\n## Evidence\n\n```\n$ true\nok\n```\n", encoding="utf-8")
    elif pid == "review":
        (tdir / "review-report.md").write_text(
            "# Review report\n\nApproved.\n", encoding="utf-8")
    elif pid == "review-lite":
        (tdir / "review-lite-report.md").write_text(
            "# Review-lite report\n\nApproved.\n", encoding="utf-8")
    elif pid == "manual":
        (tdir / "manual-checklist.md").write_text(
            "# Manual checklist\n\n- [x] passed\n", encoding="utf-8")


def _set_phase(clone: Path, ticket: str, phase: str) -> None:
    """Advance *ticket*'s meta.json to `phase` IN PLACE — every other field
    (notably any already-recorded `pre_merge_range`) survives untouched —
    and write that phase's declared output artefact so its own ack's
    completion check passes."""
    meta = _read_meta(clone, ticket)
    meta["phase"] = phase
    tdir = clone / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_phase_output(tdir, phase.split(":")[0])


def _add_commit(clone: Path, rel: str, content: str, message: str) -> None:
    """One more real commit on whatever branch is currently checked out."""
    path = clone / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", message)


def _run_ack(clone: Path, ticket: str, phase: str, *, monkeypatch, pick=1,
            persist: bool = True):
    """Point ``PROJECT_ROOT`` at *clone* and drive the real ack flow from
    ``<phase>:work``.

    ``persist=True`` (default) runs the real ``ack.run([ticket, --pick,
    ...])`` entry point — the WORK→ack-needed manual-completion branch calls
    ``phase_completion.can_complete(ticket, pid)`` with its own default
    ``persist=True`` and then recurses into the pick-based ack.
    ``persist=False`` instead calls ``phase_completion.can_complete(ticket,
    phase, persist=False)`` directly — the exact shape ``klc remind`` / the
    gate-policy advisory probe use (``core/phases/remind.py:124``) — and
    never touches ``ack.run`` at all, so it can never write anything.
    """
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    if not persist:
        import phase_completion as _pc
        return _pc.can_complete(ticket, phase, persist=False)
    import ack as _ack
    argv = [ticket, "--no-index-refresh"]
    if pick is not None:
        argv += ["--pick", str(pick)]
    return _ack.run(argv)


def _read_meta(clone: Path, ticket: str) -> dict:
    p = clone / ".klc" / "tickets" / ticket / "meta.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _meta_bytes(clone: Path, ticket: str) -> bytes:
    p = clone / ".klc" / "tickets" / ticket / "meta.json"
    return p.read_bytes()


def _rev_parse(clone: Path, ref: str) -> str:
    return _git(clone, "rev-parse", ref).strip()


def _ground_truth(clone: Path, ticket: str, *, monkeypatch, cache: dict | None = None) -> dict:
    """Call the real `phase_completion.integrate_ground_truth` resolver
    against *clone* (step-2)."""
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc
    return _pc.integrate_ground_truth(ticket, cache=cache if cache is not None else {})


def _count_git(monkeypatch):
    """A counting PASSTHROUGH around `phase_completion._git` (step-3): every
    call is logged, then delegated to the REAL original function (which
    still shells out to the real git binary) — never a canned return value
    (test-plan harness note, mock-the-real-contract rule). Returns the
    shared call-log list; each entry is the argv list passed."""
    import phase_completion as _pc
    log: list = []
    real = _pc._git

    def _wrapped(args, repo=None):
        log.append(list(args))
        return real(args, repo)

    monkeypatch.setattr(_pc, "_git", _wrapped)
    return log


def _merged_no_recording(tmp_path: Path, ticket: str,
                         commits: list[tuple[str, str, str]] | None = None) -> Path:
    """A branch with commits, merged `--ff-only` WITHOUT any recording ack
    having run — the empty-live-diff, no-usable-range starting point AC-8's
    and AC-12's degrade tests build on. Returns the clone path."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    _branch_with_commits(clone, ticket, commits or [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _merge(clone, ticket, "ff-only")
    return clone


def _merge(clone: Path, ticket: str, shape: str) -> None:
    """A REAL merge of ``feature/<ticket>`` into ``main``, then a real push to
    the bare ``origin`` (step-2). ``shape`` is one of:

    - ``"ff-only"``          — ``git merge --ff-only``.
    - ``"no-ff"``            — ``git merge --no-ff`` (a real merge commit).
    - ``"squash"``           — ``git merge --squash`` then a commit whose
      subject deliberately does NOT contain the ticket key (AC-2's
      forge-default squash reproduction, F-011).
    - ``"rebase-then-ff"``   — rebase the branch onto the CURRENT ``main`` tip,
      then ``--ff-only`` merge. For the AC-2 "rebase happens between two
      recording acks" scenario, do the rebase directly (this helper is not
      the right shape for that ordering — the test drives the rebase itself,
      between its recording acks, then calls this with ``"ff-only"``).
    """
    branch = f"feature/{ticket}"
    if shape == "rebase-then-ff":
        _git(clone, "checkout", branch)
        _git(clone, "rebase", "main")
        shape = "ff-only"
    _git(clone, "checkout", "main")
    if shape == "ff-only":
        _git(clone, "merge", "--ff-only", branch)
    elif shape == "no-ff":
        _git(clone, "merge", "--no-ff", "-m", f"Merge {branch}", branch)
    elif shape == "squash":
        _git(clone, "merge", "--squash", branch)
        _git(clone, "commit", "-m", "squash merge — see PR for details")
    else:
        raise ValueError(f"unknown merge shape {shape!r}")
    _git(clone, "push", "origin", "main")
