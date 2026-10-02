"""tests/integration/test_klc149_git_ref_selection.py — KLC-149 step-1.

`planning-eval.git_touched` must walk CODE REFS ONLY: local branches,
remote-tracking branches and tags, minus the state branch
(`core.phases.state.STATE_BRANCH`), plus the current `HEAD` unless `HEAD` is
the state branch itself. Every fixture here is a real, hermetic `tmp_path`
git repository (KLC-136: no test reads the live repository's refs or its
`.klc/`).

AC-1..AC-6, AC-15 (spec.md). Node ids are fixed by test-plan.md.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "core" / "skills" / "planning-eval.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("planning_eval_klc149", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# git fixture helpers (hermetic real git, KLC-136)
# --------------------------------------------------------------------------- #
def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(cwd))
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args} failed in {cwd}: {r.stdout}\n{r.stderr}")
    return r


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t.com"], repo)
    _git(["config", "user.name", "T"], repo)
    return repo


def _commit(repo: Path, files: dict[str, str], subject: str) -> str:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _git(["add", "-f", rel], repo)
    _git(["commit", "-m", subject], repo)
    return _git(["rev-parse", "HEAD"], repo).stdout.strip()


def _orphan_branch_commit(repo: Path, branch: str, key: str, filename: str) -> str:
    """Create *branch* as a real orphan branch (no shared history with the
    code branches — the actual `klc-state` shape) carrying one key-mentioning
    commit, leaving HEAD on *branch*."""
    _git(["checkout", "--orphan", branch], repo)
    _git(["rm", "-rf", "."], repo, check=False)
    p = repo / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("leak\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", f"{key} ack: state note"], repo)
    return _git(["rev-parse", "HEAD"], repo).stdout.strip()


def _materialize_state_branch(repo: Path, tmp_path: Path, branch: str, key: str,
                              shape: str, filename: str = "tickets/leak.txt") -> None:
    """Build an orphan state-like branch with one key-mentioning commit in the
    given ref *shape* (`'local'`, `'remote'` or `'both'`), then return HEAD to
    `main`. `'remote'` pushes into a bare clone under *tmp_path*, fetches it
    back as `origin/<branch>`, then deletes the local branch so only the
    remote-tracking ref remains (test-plan AC-1 remote-only row)."""
    _orphan_branch_commit(repo, branch, key, filename)
    if shape in ("remote", "both"):
        bare = tmp_path / f"{branch.replace('/', '-')}-origin.git"
        if not bare.exists():
            _git(["init", "--bare", str(bare)], tmp_path)
            _git(["remote", "add", "origin", str(bare)], repo)
        _git(["push", "origin", branch], repo)
        _git(["fetch", "origin"], repo)
    _git(["checkout", "main"], repo)
    if shape == "remote":
        _git(["branch", "-D", branch], repo)


def _seed(repo: Path) -> None:
    _commit(repo, {"README.md": "seed\n"}, "seed: init")


# --------------------------------------------------------------------------- #
# AC-1 — the state branch (local / remote / both) is excluded
# --------------------------------------------------------------------------- #
def test_state_branch_local_only_excluded(tmp_path):
    """AC-1: a key-mentioning commit reachable ONLY via `refs/heads/<state>`
    (no remote-tracking ref exists at all) contributes no file."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9001"
    _commit(repo, {"src/good.py": "x=1\n"}, f"{key} step-1: good file")
    _materialize_state_branch(repo, tmp_path, "klc-state", key, "local")

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert "src/good.py" in files
    assert "tickets/leak.txt" not in files


def test_state_branch_remote_only_excluded(tmp_path):
    """AC-1: the same commit exists ONLY as `refs/remotes/origin/<state>`
    (the local branch is deleted after a bare clone fetches it in, so no
    local ref can be masking the result) — still excluded."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9002"
    _commit(repo, {"src/good.py": "x=1\n"}, f"{key} step-1: good file")
    _materialize_state_branch(repo, tmp_path, "klc-state", key, "remote")

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert "src/good.py" in files
    assert "tickets/leak.txt" not in files


def test_state_branch_local_and_remote_ref_excluded(tmp_path):
    """AC-1 literal wording: the state-like branch exists both as
    `refs/heads/<state>` and as a fabricated `refs/remotes/origin/<state>` at
    once (F-004's `git log --all` reproduction shape); no path from either
    ref is returned."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9003"
    _commit(repo, {"src/good.py": "x=1\n"}, f"{key} step-1: good file")
    _materialize_state_branch(repo, tmp_path, "klc-state", key, "both")

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert "src/good.py" in files
    assert "tickets/leak.txt" not in files


# --------------------------------------------------------------------------- #
# AC-2 — the worktree-HEAD leak (F-004's actual repro shape)
# --------------------------------------------------------------------------- #
def test_second_worktree_on_state_branch_excluded(tmp_path):
    """AC-2: the state-like branch is checked out in a second linked
    worktree while the MAIN worktree sits on a code branch — `--all` used to
    leak that worktree's HEAD in; the fix must hold even from the main
    worktree."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9004"
    _commit(repo, {"src/good.py": "x=1\n"}, f"{key} step-1: good file")
    _orphan_branch_commit(repo, "klc-state", key, "tickets/leak.txt")
    _git(["checkout", "main"], repo)
    wt = tmp_path / "state-worktree"
    _git(["worktree", "add", str(wt), "klc-state"], repo)

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert "src/good.py" in files
    assert "tickets/leak.txt" not in files


# --------------------------------------------------------------------------- #
# AC-3 — a ticket matched only by state commits is a real derivation gap
# --------------------------------------------------------------------------- #
def test_ticket_touched_files_state_only_returns_none(tmp_path):
    """AC-3: a ticket whose only key-mentioning commits are on the state
    branch, with no stored patch, derives `([], False, "none")` — the
    fail-closed shape the backfill turns into an `unavailable` row, not a
    silently-scored empty footprint."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9005"
    _orphan_branch_commit(repo, "klc-state", key, "tickets/leak.txt")
    _git(["checkout", "main"], repo)

    ticket_dir = tmp_path / "ticket"
    ticket_dir.mkdir()
    result = pe.ticket_touched_files(key, ticket_dir, repo)
    assert result == ([], False, "none")


# --------------------------------------------------------------------------- #
# AC-4 — unmerged / remote-only / tag-only commits still count (pins)
# --------------------------------------------------------------------------- #
def test_unmerged_local_branch_still_counted(tmp_path):
    """AC-4 (pin): a key-mentioning commit on an unmerged local branch,
    nothing checked out on it, is still returned — code refs stay in scope."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9006"
    _git(["checkout", "-b", "feature/unmerged"], repo)
    _commit(repo, {"src/feat.py": "x=1\n"}, f"{key} step-1: feature work")
    _git(["checkout", "main"], repo)

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert files == ["src/feat.py"]


def test_remote_tracking_only_branch_still_counted(tmp_path):
    """AC-4 (pin): the key-mentioning commit exists only as a
    `refs/remotes/origin/*` ref with no matching local branch; still
    returned."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9007"
    _git(["checkout", "-b", "feature/remote-only"], repo)
    _commit(repo, {"src/feat.py": "x=1\n"}, f"{key} step-1: feature work")
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], tmp_path)
    _git(["remote", "add", "origin", str(bare)], repo)
    _git(["push", "origin", "feature/remote-only"], repo)
    _git(["fetch", "origin"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "feature/remote-only"], repo)

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert files == ["src/feat.py"]


def test_tag_only_commit_still_counted(tmp_path):
    """AC-4 (pin): the key-mentioning commit is reachable only via an
    annotated tag, no branch points at it; still returned."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9008"
    _git(["checkout", "-b", "tmp-tag-branch"], repo)
    _commit(repo, {"src/feat.py": "x=1\n"}, f"{key} step-1: tagged work")
    _git(["tag", "-a", "v-klc9008", "-m", "tag"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "tmp-tag-branch"], repo)

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert files == ["src/feat.py"]


# --------------------------------------------------------------------------- #
# AC-5 — no path-name filtering (language-agnostic, C-005)
# --------------------------------------------------------------------------- #
def test_tickets_and_index_prefixed_code_paths_not_filtered(tmp_path):
    """AC-5 (pin): a key-mentioning commit on a CODE branch touches
    `tickets/foo.py` and `index/bar.py`; both are kept — this is a ref-scope
    rule, not a path-name filter."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9009"
    _commit(repo, {"tickets/foo.py": "x=1\n", "index/bar.py": "x=2\n"},
            f"{key} step-1: layout-named code paths")

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert "tickets/foo.py" in files
    assert "index/bar.py" in files


# --------------------------------------------------------------------------- #
# AC-6 — the state ref name comes from core.phases.state.STATE_BRANCH
# --------------------------------------------------------------------------- #
def test_exclusion_follows_patched_state_branch_constant(tmp_path, monkeypatch):
    """AC-6: patching `STATE_BRANCH` to a different literal retargets the
    exclusion (the new-literal branch's files are excluded) AND the old name
    `klc-state` loses its special status (a branch literally named
    `klc-state`, present in the SAME run, is no longer excluded). Also: an
    AST scan asserts `planning-eval.py` holds no `"klc-state"` string
    constant (F-006 — the name is read from the constant, never re-declared)."""
    pe = _load_skill()
    monkeypatch.setattr(pe._state, "STATE_BRANCH", "ticket-state")
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9010"
    _orphan_branch_commit(repo, "ticket-state", key, "tickets/leak-new.txt")
    _git(["checkout", "main"], repo)
    _orphan_branch_commit(repo, "klc-state", key, "tickets/leak-old.txt")
    _git(["checkout", "main"], repo)

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert "tickets/leak-new.txt" not in files
    assert "tickets/leak-old.txt" in files

    src = _SKILL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    literal_hits = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and n.value == "klc-state"]
    assert literal_hits == [], f"planning-eval.py must not re-declare the state branch name: {literal_hits}"


# --------------------------------------------------------------------------- #
# AC-15 — HEAD and bare-repo edge cases
# --------------------------------------------------------------------------- #
def test_detached_head_only_reachable_commit_included(tmp_path):
    """AC-15a (pin): a key commit reachable only from a detached HEAD is
    included (A-002: covers a CI clone with no local branches)."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9011"
    _git(["checkout", "-b", "tmp-detach"], repo)
    _commit(repo, {"src/feat.py": "x=1\n"}, f"{key} step-1: detached work")
    sha = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _git(["checkout", sha], repo)
    _git(["branch", "-D", "tmp-detach"], repo)

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert files == ["src/feat.py"]


def test_head_on_state_branch_contributes_nothing(tmp_path):
    """AC-15b: the `--repo` checkout's current HEAD is the state-like branch
    itself; it contributes nothing — excluded like any other state ref, not
    specially re-included because it is HEAD."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9012"
    _orphan_branch_commit(repo, "klc-state", key, "tickets/leak.txt")
    # HEAD is left on klc-state.

    files, present = pe.git_touched(key, repo)
    assert files == []
    assert present is False


def test_no_remotes_no_tags_no_state_branch_unchanged(tmp_path):
    """AC-15c (pin): a repo with no remote, no tag and no state branch at
    all still derives exactly the same files a direct `git log --all` probe
    would (the degrade-to-today's-behaviour edge)."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9013"
    _commit(repo, {"src/feat.py": "x=1\n"}, f"{key} step-1: plain work")

    files, present = pe.git_touched(key, repo)
    grep = f"--grep=(^|[^0-9A-Za-z]){key}([^0-9A-Za-z]|$)"
    r = _git(["log", "--all", "-E", grep, "--name-only", "--pretty=format:"], repo)
    direct_files = sorted({ln.strip() for ln in r.stdout.splitlines() if ln.strip()})

    assert present is True
    assert files == direct_files
    assert files == ["src/feat.py"]


def test_failing_git_call_still_degrades_to_empty_not_raise(tmp_path):
    """AC-15 (pin): a `--repo` path that is not a git work tree makes
    `git_touched` degrade to `([], False)`, never raise — the pre-existing
    `planning-eval.py:145-146` contract must survive the rewrite unchanged."""
    pe = _load_skill()
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()

    files, present = pe.git_touched("KLC-9014", not_a_repo)
    assert files == []
    assert present is False


# --------------------------------------------------------------------------- #
# step-6 — review round 1: exact-per-remote exclusion, negative revisions
# --------------------------------------------------------------------------- #
def test_remote_branch_named_like_state_suffix_not_excluded(tmp_path):
    """external review F-2: `--exclude=*/<state>` used to overmatch, because
    `*` matches `/` in git's glob — a remote branch `feature/<state>`
    (pushed to `origin`, giving `refs/remotes/origin/feature/klc-state`) is
    not the state branch itself and must stay walked. The fix excludes one
    literal `<remote>/<state>` per configured remote instead of a glob."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9015"
    _git(["checkout", "-b", "feature/klc-state"], repo)
    _commit(repo, {"src/feat.py": "x=1\n"}, f"{key} step-1: feature work")
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], tmp_path)
    _git(["remote", "add", "origin", str(bare)], repo)
    _git(["push", "origin", "feature/klc-state"], repo)
    _git(["fetch", "origin"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "feature/klc-state"], repo)

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert files == ["src/feat.py"]


def test_tag_literally_named_state_branch_excluded(tmp_path):
    """code review F-1: a tag literally named the same as the state branch
    (`core.phases.state.STATE_BRANCH`) is excluded too — before this fix,
    `--exclude` was spliced only ahead of `--branches` and `--remotes`,
    never `--tags`, so a tag named `klc-state` slipped through by name and
    its commit (unreachable from any other code ref here) leaked in."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9016"
    _git(["checkout", "-b", "tmp-tag-only"], repo)
    _commit(repo, {"tickets/leak.txt": "leak\n"}, f"{key} ack: tag-only work")
    _git(["tag", "klc-state"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "tmp-tag-only"], repo)

    files, present = pe.git_touched(key, repo)
    assert files == []
    assert present is False


def test_tag_on_state_commit_excluded(tmp_path):
    """external review F-3: a tag with an ORDINARY name pointing directly at
    the state branch's tip commit still leaves that commit's files out.
    `--exclude` (`_code_ref_args`) only governs which ref a glob option
    STARTS walking from — it says nothing about history reached some other,
    unexcluded way. Commit-identity filtering (`_state_only_commits`, which
    replaced step-6's reachability-based `_state_exclusion_revs` in step-7)
    closes that gap."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9017"
    state_sha = _orphan_branch_commit(repo, "klc-state", key, "tickets/leak.txt")
    _git(["tag", "v-on-state", state_sha], repo)
    _git(["checkout", "main"], repo)

    files, present = pe.git_touched(key, repo)
    assert "tickets/leak.txt" not in files
    assert files == []
    assert present is False


def test_detached_head_at_state_commit_excluded(tmp_path):
    """external review F-3 twin: a detached `HEAD` checked out directly at
    the state branch's tip commit (not via the branch name) must not
    resurrect it — the detached-HEAD inclusion rule (AC-15a) must not
    override the state-branch exclusion just because HEAD itself now
    'reaches' that commit."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9018"
    state_sha = _orphan_branch_commit(repo, "klc-state", key, "tickets/leak.txt")
    _git(["checkout", state_sha], repo)  # detached HEAD, not the branch name

    files, present = pe.git_touched(key, repo)
    assert "tickets/leak.txt" not in files
    assert files == []
    assert present is False


# --------------------------------------------------------------------------- #
# step-7 — review round 2 external F-1: state-only exclusion must be
# commit-identity-based, not reachability-based, so it does not drop
# history a state branch merely SHARES with a code branch
# --------------------------------------------------------------------------- #
def test_state_branch_forked_from_main_main_commit_still_counted(tmp_path):
    """external review F-1: the state-like branch is forked FROM `main`
    with `checkout -b` (NOT an orphan — the live `klc-state` is an orphan;
    this covers the case a reachability-based `^refs/heads/<state>`
    negative revision silently breaks). `main`'s key-mentioning commit is
    an ANCESTOR of the state branch's tip too, but it is still reachable
    from `main` directly, so it must stay in scope; the state-only commit
    made on the forked branch itself must still be excluded."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9019"
    _commit(repo, {"src/good.py": "x=1\n"}, f"{key} step-1: good file")
    _git(["checkout", "-b", "klc-state"], repo)
    _commit(repo, {"tickets/unrelated.txt": "x\n"}, f"{key} ack: unrelated state note")
    _git(["checkout", "main"], repo)

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert "src/good.py" in files
    assert "tickets/unrelated.txt" not in files


def test_main_merged_into_state_branch_main_commit_still_counted(tmp_path):
    """external review F-1 twin: `main` is later merged INTO the
    (non-orphan) state branch. `main`'s key-mentioning commit is reachable
    from `main` directly AND from the state branch via the merge, but it
    must still be returned — only a commit reachable from NO code branch
    is state-only, never one reachable from both."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9020"
    _commit(repo, {"src/good.py": "x=1\n"}, f"{key} step-1: good file")
    _git(["checkout", "-b", "klc-state"], repo)
    _commit(repo, {"tickets/unrelated.txt": "x\n"}, f"{key} ack: unrelated state note")
    _git(["checkout", "main"], repo)
    _commit(repo, {"src/more.py": "x=2\n"}, "chore: unrelated main work")
    _git(["checkout", "klc-state"], repo)
    _git(["merge", "main", "-m", "merge main into klc-state"], repo)
    _git(["checkout", "main"], repo)

    files, present = pe.git_touched(key, repo)
    assert present is True
    assert "src/good.py" in files
    assert "tickets/unrelated.txt" not in files


# --------------------------------------------------------------------------- #
# step-8 — review round 3 external F-1: a failure of the state-only
# rev-list probe itself must fail CLOSED, never be treated like "nothing is
# state-only"
# --------------------------------------------------------------------------- #
def test_state_only_rev_list_failure_fails_closed(tmp_path, monkeypatch, capsys):
    """review round 3 external F-1: `_state_only_commits`' own `git rev-list
    <state refs> --not <branch refs>` call can itself fail (a corrupt odb, a
    git version missing a flag, ...) even though a state ref resolved just
    fine. Before this fix that failure was treated exactly like "nothing is
    state-only" (`return set()`), so `git_touched` kept whatever state-only
    commit the tag/HEAD gap (external review F-3, covered by
    `test_tag_on_state_commit_excluded` above when the SAME rev-list call
    succeeds) exists precisely to drop — silently reporting a clean recall
    instead of a derivation gap. The fix fails CLOSED: `git_touched` returns
    `([], False)` and warns once on stderr, naming the ticket and the
    failed command."""
    pe = _load_skill()
    repo = _make_repo(tmp_path)
    _seed(repo)
    key = "KLC-9021"
    state_sha = _orphan_branch_commit(repo, "klc-state", key, "tickets/leak.txt")
    _git(["tag", "v-on-state", state_sha], repo)
    _git(["checkout", "main"], repo)

    real_git = pe._git

    def failing_git(args, repo_arg):
        if args and args[0] == "rev-list" and "--not" in args:
            return 1, ""
        return real_git(args, repo_arg)

    monkeypatch.setattr(pe, "_git", failing_git)

    files, present = pe.git_touched(key, repo)
    assert files == []
    assert present is False
    err = capsys.readouterr().err
    assert key in err
    assert "rev-list" in err
