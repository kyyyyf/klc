#!/usr/bin/env python3
"""ac_test_coverage.py — AC→implemented-test coverage gate at build (KLC-095, V-02).

KLC-085's `testplan_review.coverage_map` proves each SAOC acceptance criterion is
covered in the test PLAN. This skill is its EXECUTION double: it proves the
planned coverage actually LANDED — that every AC maps to a REAL implemented test
which references the AC-id by the existing project convention AND is collected and
passing. An AC with no implemented passing test is an OBJECTIVE coverage miss, the
same class of objective defect that `tdd_order.verify_step` already blocks on at
build; on M/L it BLOCKS the build ack (with an operator override), on S it only
surfaces, on XS it is off.

Single source of truth (C-001) — this module CALLS three already-merged seeds and
re-implements none of them:
  * `spec_saoc.parse_acs`            — the ONLY parser of the ACs.
  * `testplan_review.coverage_map`   — the ONLY source of plan-declared test
    locations (it already applies `parse_coverage_rows` + `CoverageRow.has_real_test`
    to drop `—`/`TBD`/empty placeholders).
  * `testplan_review._AC_ID_RE`      — the same `AC-\\d+` class for the canonical id.

The AC-id convention has TWO forms and both are accepted (C-001):
  1. the AC-id token in the test FUNCTION NAME, lowercase no-dash, as a BOUNDED
     token so `ac1` != `ac10` (e.g. `def test_ac1_acquire_when_absent(...)`).
  2. the canonical `AC-<n>` in the test DOCSTRING/body (the dominant form).

Single-ticket scope (FIX-1): AC ids are NOT globally unique — every ticket restarts
at AC-1 — so the AC-id scan is limited to THIS ticket's own test files (the
plan-declared coverage locations plus the ticket's changed `tests/…py`), never a
repo-wide grep that another ticket's `test_ac1_*` would satisfy. When that candidate
set is EMPTY (no plan locations and no changed test files), the gate cannot locate
the ticket's tests, so an apparently-uncovered AC is UNDETERMINED, not an objective
miss: it degrades to a single SURFACE note and never blocks (no-false-block — a
shallow clone plus an empty coverage table must not block a genuinely-tested ticket).

Existence + passing (C-005 / Q-002): the "test exists and passes" check is SCOPED to
only the node-ids tied to the ticket's ACs — `--collect-only` per file as the cheap
existence floor, then a targeted `pytest -v` over those node-ids. A node counts as
passing ONLY when it genuinely PASSED (a skip/xfail is NOT passing), attributed by
exact node-id. It NEVER runs the whole suite, and it runs ONLY on the real ack path
(a read-only probe does the static classification with no pytest — FIX-2).

THE STRUCTURAL INVARIANT (this is a BLOCKING gate on M/L, so the false-block class
is closed by construction, not by patching git edges one at a time): git-discovered
changed files are a STRICTLY ADDITIVE supplement to COVERAGE — they may only turn a
would-be-miss into COVERED; they are NEVER required for correctness and NEVER
substantiate a block. A confident BLOCK is substantiated ONLY from the PLAN-declared
locations (from `coverage_map`, which KLC-085 requires filled for M/L): the plan
named a real test file for the AC, that file was successfully scanned, and it
contains no referencing test. Therefore NO git condition — wrong repo/CWD, no
merge-base, shallow, untracked-omitted, error, empty — can produce a MISS→block; the
worst case a git gap causes is a surface that could have been cleared. Git for the
supplement runs in the PROJECT repo (PROJECT_ROOT / the `repo` param), never the
process CWD, and honors the `repo` override end-to-end (discovery AND scanning).

Degrade-not-fail (C-003): a missing/malformed `spec.md` or `test-plan.md`, or any
pytest-invocation surprise, degrades to a single SURFACE note (or a WEAK/surface AC
when a referencing test could not be confirmed passing) and never blocks or crashes
the build ack. An empty candidate set, an unreadable/unparseable plan-declared file,
or a plan that declares no location for the AC → SURFACE (undetermined), never BLOCK.

Track scaling (C-004, track = floor): OFF on XS, SURFACE-only on S, BLOCK on M/L —
resolved INSIDE the skill from the passed track, mirroring
`testplan_review._active_dimensions`.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Package-safe path setup (mirrors testplan_review.py): make both the project root
# and this skills dir importable so bare `import spec_saoc` resolves under script
# AND package invocation.
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
for _p in (str(_project_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import spec_saoc as _saoc  # noqa: E402
import testplan_review as _tpr  # noqa: E402
import settings  # noqa: E402  (KLC-115: verify.node_budget_seconds / verify.arm_budget_seconds)
import verify_runner  # noqa: E402  (KLC-115: the bounded, language-agnostic runner)
import test_conventions as _tc  # noqa: E402  (KLC-109: the shared test-path table)

# Reuse the SAME AC-id class the plan review anchors on — no second parser (C-001).
_AC_ID_RE = _tpr._AC_ID_RE  # AC-\d+

SURFACE = "surface"
BLOCK = "block"

# pytest per-test outcome tokens, as printed on a `-v` progress line
# (`<nodeid> PASSED`) or a summary line (`PASSED <nodeid>`).
_PYTEST_OUTCOMES = frozenset({"PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS"})

# Coverage states, in worsening order.
COVERED = "covered"
DRIFT = "drift"
WEAK = "weak"
MISS = "miss"
UNVERIFIED = "unverified"        # KLC-115 D-201: the gate could not observe

# D-201: only these reasons mean "the gate could not observe" — `skipped` and
# `uncollected` are DEFINITE negative observations and keep today's WEAK
# treatment, so a skipped test still cannot evade the gate (F-104).
_INCONCLUSIVE = frozenset({"slow", "arm-budget-exhausted",
                          "launch-error", "runner-unavailable"})


def _ac_num(ac_id: str) -> str:
    """The bare number of an AC id: `AC-10` -> `10`. Empty when unparseable."""
    parts = ac_id.split("-", 1)
    return parts[1] if len(parts) == 2 else ""


def _name_re(num: str) -> re.Pattern:
    """Bounded `ac<n>` matcher for a test FUNCTION NAME.

    The boundaries reject an adjacent LETTER OR DIGIT on both sides (FIX-B), so
    `ac1` matches neither `ac10` (trailing digit) nor `ac1beta` (trailing letter),
    while a separator like `_` is still fine (`ac1_foo` OK). `_` is not alphanumeric
    so it is not part of the token.
    """
    return re.compile(rf"(?<![a-z0-9])ac{num}(?![a-z0-9])", re.IGNORECASE)


def _body_re(num: str) -> re.Pattern:
    """Canonical `AC-<n>` matcher for a test DOCSTRING/body — the same `AC-\\d+`
    shape as `testplan_review._AC_ID_RE`, pinned to this AC's number and bounded on
    the right against a LETTER OR DIGIT (FIX-B): `AC-1` matches neither `AC-10` nor
    `AC-1a`, while a separator (`AC-1.`, `AC-1 `, `AC-1:`, `AC-1/`) is still fine."""
    return re.compile(rf"AC-{num}(?![A-Za-z0-9])")


# ---------------------------------------------------------------------------
# Static scan: each AC → the implemented tests that reference it (node-ids).
# ---------------------------------------------------------------------------

def _iter_test_functions(tree: ast.AST, source: str):
    """Yield (qualname, source_segment) for each `test*` function in *tree*.

    Handles module-level functions and one level of class nesting (the two shapes
    pytest test files use). The caller parses (so a parse error is visible as an
    incomplete scan), never this helper.
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                yield node.name, ast.get_source_segment(source, node) or ""
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test"):
                    yield f"{node.name}::{sub.name}", ast.get_source_segment(source, sub) or ""


def _resolve_candidate(cand: str, tests_root: Path, project_root: Path) -> Path | None:
    """Resolve a candidate path string to an existing file, trying it as
    project-root-relative (`pkg/tests/test_x.py`, `tests/test_x.py`) then
    tests-root-relative then absolute. None if no such file exists."""
    p = Path(cand)
    tries = [p] if p.is_absolute() else [project_root / cand, tests_root / cand]
    for t in tries:
        if t.is_file():
            return t
    return None


def _scan_tests_for_ac_ids(tests_root, ac_ids: list[str], candidate_files,
                           repo=None) -> tuple[dict[str, list[str]], set[str]]:
    """Map each AC id to the node-ids of implemented tests referencing it, SCOPED to
    *candidate_files* — THIS ticket's own test files. Returns (implemented, scanned).

    A test references AC-n when its function NAME carries the bounded `ac<n>` token
    OR its DOCSTRING/body carries the canonical `AC-<n>`. The scan is limited to
    *candidate_files* (the plan-declared locations + the ticket's changed test files)
    rather than the whole `tests/` tree, because AC ids are NOT globally unique
    (every ticket restarts at AC-1) — a repo-wide grep would let another ticket's
    `test_ac1_*` falsely mark this ticket's AC-1 covered (FIX-1). Each candidate is
    read AT ITS ACTUAL PATH, resolved against *repo* if given else the project root
    (FIX-A: `check(repo=…)` must scan candidates in THAT repo, and a NESTED monorepo
    tests dir like `pkg/tests/test_x.py` is scanned too). Node-ids are project-root-
    relative so a scoped pytest run resolves them.

    *scanned* is the set of candidate strings that RESOLVED to a real file and were
    read + parsed successfully. It substantiates a confident miss: the caller may
    block an AC only when one of its PLAN-declared files is in *scanned* and contains
    no referencing test — a git-independent basis. A candidate that does not exist,
    cannot be read, or fails to parse is simply absent from *scanned* (never a block
    basis); reading/parse errors thus degrade to surface, not block.
    """
    result: dict[str, list[str]] = {ac: [] for ac in ac_ids}
    scanned: set[str] = set()
    if not candidate_files:
        return result, scanned
    tests_root = Path(tests_root)
    project_root = Path(repo) if repo is not None else tests_root.parent
    nums = {ac: _ac_num(ac) for ac in ac_ids}
    name_res = {ac: _name_re(nums[ac]) for ac in ac_ids if nums[ac]}
    body_res = {ac: _body_re(nums[ac]) for ac in ac_ids if nums[ac]}
    ok_paths: set[Path] = set()
    bad_paths: set[Path] = set()
    for cand in candidate_files:
        path = _resolve_candidate(cand, tests_root, project_root)
        if path is None:
            continue  # a declared-but-absent test → drift territory, never a block basis
        if path.suffix != ".py":
            # KLC-109 AC-9: a non-python candidate (discovery is now
            # language-agnostic, via test_conventions) is ADMITTED here but
            # never parsed, never enters `scanned`, and can therefore never
            # substantiate a block — pytest node-id verification stays
            # python-only per the Non-goals.
            continue
        rp = path.resolve()
        if rp in ok_paths:
            scanned.add(cand)  # same file, different spelling — still successfully scanned
            continue
        if rp in bad_paths:
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            bad_paths.add(rp)  # unreadable/unparseable → not a confident-miss basis
            continue
        ok_paths.add(rp)
        scanned.add(cand)
        try:
            node_rel = path.relative_to(project_root).as_posix()
        except ValueError:
            node_rel = cand if not Path(cand).is_absolute() else path.name
        for qualname, seg in _iter_test_functions(tree, source):
            func_name = qualname.rsplit("::", 1)[-1]
            for ac in ac_ids:
                if ac not in name_res:
                    continue
                if name_res[ac].search(func_name) or body_res[ac].search(seg):
                    result[ac].append(f"{node_rel}::{qualname}")
    return result, scanned


# --- deriving THIS ticket's candidate test files ----------------------------

_PY_RE = re.compile(r"[\w./-]+\.py")


def _plan_files(planned: dict[str, list[str]]) -> set[str]:
    """The `.py` test files named in the plan-declared coverage locations.

    Extracts EVERY `.py` path in a location cell, not just the first (FIX-A): a cell
    may list several test files (e.g. two node-ids), and the AC's real test can live
    in the second — all of them must join the candidate set or that test is never
    scanned and the AC is falsely reported drift/weak."""
    out: set[str] = set()
    for locs in planned.values():
        for loc in locs:
            out.update(_PY_RE.findall(str(loc)))
    return out


def _git(args: list[str], repo=None) -> tuple[str, bool]:
    """Run git; return (stdout, ok) where ok is True iff git exited 0. `ok` lets the
    caller distinguish a positively-confirmed empty result from a FAILURE — the two
    must never be conflated (a failure is uncertainty, not "no changes")."""
    try:
        r = subprocess.run(["git"] + args, capture_output=True, text=True,
                           cwd=str(repo) if repo else None, timeout=30)
        return r.stdout, r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return "", False


def _head_tree_members(cwd: Path) -> frozenset[str]:
    """The set of paths in HEAD's git tree (``git ls-tree -r --name-only
    HEAD``) — the sibling-existence probe `_changed_test_files` passes as
    `exists=` (KLC-109 review-fix round 2, D-109-10, drift F-4).

    Never `Path.exists()` on a path list that came from git: a basename-only
    match (e.g. `core/skills/test_conventions.py`'s own `test_*.py`-shaped
    filename) is confirmed a test only when its derived sibling
    (`conventions.py`) already existed in HEAD's tree BEFORE this diff — a
    stable, git-object-backed answer, never today's live working-tree
    checkout. This is strictly additive supplementary evidence (the module
    docstring's STRUCTURAL INVARIANT): a colocated pair added together in
    the SAME uncommitted diff (sibling not yet in HEAD) simply does not get
    counted here — no git condition can turn that into a false BLOCK, it
    only means one fewer additive candidate. Returns an empty frozenset on
    any git failure (never raises)."""
    out, ok = _git(["ls-tree", "-r", "--name-only", "HEAD"], cwd)
    if not ok:
        return frozenset()
    return frozenset(line.strip() for line in out.splitlines() if line.strip())


def _repo_root(repo=None) -> Path:
    """The git working directory for changed-file discovery: the explicit *repo* if
    given, else the PROJECT root the ticket/tests are read from — NEVER the process
    CWD. Running git in the process CWD (the old `repo=None` default) would, in the
    multi-project layout or any invocation launched outside the project repo, run git
    in the wrong repo and silently miss THIS ticket's changed tests."""
    if repo is not None:
        return Path(repo)
    try:
        from core.shared.paths import project_root
        return project_root()
    except Exception:
        return _project_root


def _changed_test_files(repo=None) -> set[str] | None:
    """The ticket's changed `tests/…py` files (committed vs the default base plus the
    working tree), a best-effort supplement to the plan-declared locations. Git runs
    in the PROJECT repo (`_repo_root`), not the process CWD.

    CONVERGING PRINCIPLE (so this false-block class stays closed): return a concrete
    set ONLY when the result is POSITIVELY confirmed complete — a working git repo, a
    diff base actually established against origin/main or main, AND every diff command
    exited cleanly. ANY inability to establish that — git missing / not a repo, no
    merge-base found (a shallow/detached/unborn feature-branch clone), or any git
    error — returns None (UNAVAILABLE). There is deliberately NO path where an
    incomplete/uncertain git result is returned as an empty set and later read as
    "complete, no changes": that empty-but-uncertain set is exactly what let a
    plan-unlisted-but-implemented AC false-block. Never raises."""
    cwd = _repo_root(repo)
    # Availability probe: a working (non-bare) git repo we can query?
    out, ok = _git(["rev-parse", "--is-inside-work-tree"], cwd)
    if not ok or out.strip() != "true":
        return None
    # Positively establish a diff base against origin/main or main.
    base = None
    for ref in ("origin/main", "main"):
        mb, ok = _git(["merge-base", "HEAD", ref], cwd)
        if ok and mb.strip():
            base = mb.strip()
            break
    if base is None:
        return None  # no confirmable base → uncertain → unavailable, never empty
    table = _tc.active_table()        # D-203: the same table every other gate uses
    # KLC-109 review-fix round 2 (D-109-10, drift F-4): a GATE-adjacent
    # consumer opts in with exists= backed by HEAD's git tree, never a bare
    # default call (which would let a `test_signal`-shaped production
    # function in `core/skills/test_conventions.py` satisfy the discovery
    # filter on a coincidental AC-id token match — the exact drift finding).
    head_members = _head_tree_members(cwd)
    files: set[str] = set()
    for args in (
        ["diff", "--name-only", f"{base}..HEAD"],       # committed vs base
        ["diff", "--name-only", "HEAD"],                # unstaged (tracked)
        ["diff", "--name-only", "--cached"],            # staged
        ["ls-files", "--others", "--exclude-standard"],  # brand-new UNTRACKED (FIX-B)
    ):
        block, ok = _git(args, cwd)
        if not ok:
            return None  # any command failure → uncertain → unavailable, never partial
        for line in block.splitlines():
            s = line.strip()
            # KLC-109 AC-9: discovery goes through the shared convention module
            # (was: `.py` + a `tests/`-prefix/substring check) — so a colocated
            # non-python test (`src/Foo.test.tsx`) is admitted on a project with
            # no top-level `tests/` directory. Python-only parsing/verification
            # still happens downstream, in `_scan_tests_for_ac_ids`.
            if s and _tc.is_test_path(s, table=table, exists=head_members.__contains__):
                files.add(s)
    return files


def _candidate_files(planned: dict[str, list[str]], repo=None) -> set[str]:
    """THIS ticket's candidate test files to SCAN = the plan-declared locations UNION
    the ticket's changed test files. Scoping the AC-id scan to these (not the whole
    tree) is what makes the gate reconcile plan→execution for THIS ticket (FIX-1).

    THE INVARIANT: the git-discovered changed files are a STRICTLY ADDITIVE supplement
    to COVERAGE — they can only turn a would-be-miss into COVERED, never substantiate a
    block. So git's completeness/availability is irrelevant here (an unavailable git
    just contributes nothing); a confident BLOCK is substantiated separately, from the
    PLAN-declared locations that were successfully scanned (see `_scan_tests_for_ac_ids`
    `scanned` and `_evaluate`). No git condition can therefore force a MISS→block."""
    return _plan_files(planned) | (_changed_test_files(repo) or set())


# ---------------------------------------------------------------------------
# step-1 public API: the static covered/drift/miss classification.
# ---------------------------------------------------------------------------

def build_map(spec_text: str, test_plan_text: str, tests_root,
              candidate_files=None) -> dict[str, str]:
    """Classify each SAOC AC as covered / drift / miss (STATIC — no passing check).

    * covered — an implemented test in THIS ticket's files references the AC.
    * drift   — no implemented test references it, but the plan (coverage_map)
                declared a real test location for it (the plan claimed it, the code
                did not land it).
    * miss    — no implemented test AND no plan-declared location.

    *candidate_files* scopes the scan to THIS ticket's own test files; when omitted
    it defaults to the plan-declared locations (FIX-1: never a repo-wide grep, since
    AC ids are not globally unique). ACs come only through `spec_saoc.parse_acs`;
    plan locations only through `testplan_review.coverage_map` (C-001).
    """
    ac_ids = [ac.id for ac in _saoc.parse_acs(spec_text or "")]
    planned = _tpr.coverage_map(spec_text or "", test_plan_text or "")
    if candidate_files is None:
        candidate_files = _plan_files(planned)
    implemented, _scanned = _scan_tests_for_ac_ids(tests_root, ac_ids, candidate_files)
    out: dict[str, str] = {}
    for ac in ac_ids:
        if implemented.get(ac):
            out[ac] = COVERED
        elif planned.get(ac):
            out[ac] = DRIFT
        else:
            out[ac] = MISS
    return out


# ---------------------------------------------------------------------------
# The "test exists + passes" mechanism (C-005 / Q-002): a SCOPED pytest run.
# ---------------------------------------------------------------------------

def _collect_existing(node_ids, repo, tests_root) -> set[str]:
    """The existence floor, isolated PER FILE (extracted unchanged from the
    original `_verify_passing`, F-103): a single unresolvable node-id aborts a
    whole pytest selection with "not found", so collecting the batch as one
    selection would let one bad id mark EVERY passing test not-passing.
    Collecting a FILE never fails on a bad node-id, so each requested node-id
    is resolved against its own file's collection; an unresolvable id then
    affects only itself (Codex MEDIUM fix)."""
    cwd = None
    if repo is not None:
        cwd = str(repo)
    elif tests_root is not None:
        cwd = str(Path(tests_root).parent)
    base = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider"]
    by_file: dict[str, list[str]] = {}
    for n in node_ids:
        by_file.setdefault(n.split("::", 1)[0], []).append(n)
    collected: set[str] = set()
    for f, nodes in by_file.items():
        try:
            col = subprocess.run(base + [f, "--collect-only", "-q"],
                                 capture_output=True, text=True, cwd=cwd, timeout=120)
        except Exception:
            continue  # pytest unavailable / file surprise → those nodes stay unconfirmed
        col_out = (col.stdout or "") + (col.stderr or "")
        collected.update(n for n in nodes if n in col_out)
    return collected


def _attribute_outcomes(run_out: str, nodes) -> tuple[set[str], set[str]]:
    """The EXISTING FIX-3/FIX-5/FIX-B attribution loop (F-103), extracted out
    of `_verify_passing` UNCHANGED so both the boolean path (`_verify_passing`)
    and the tri-state path (`_verify_nodes`) read ONE parser (D-201). Returns
    (passed_any, bad_any): a `-v` progress line `<nodeid> <OUTCOME>` or a
    summary line `<OUTCOME> <nodeid>` is located by its outcome TOKEN, the
    node-id is reconstructed around it, and a parametrised variant
    `node[param]` attributes to its base node. SKIPPED and XFAIL add to
    NEITHER set, which is exactly why a skip is not a pass (FIX-3)."""
    passed_any: set[str] = set()
    bad_any: set[str] = set()
    node_set = set(nodes)
    for line in run_out.splitlines():
        tokens = line.split()
        # A parametrised node-id may contain SPACES (`test_ac1[case one]`), so we
        # never trust a fixed token position (FIX-B). Locate the outcome TOKEN and
        # reconstruct the node-id around it, for BOTH the `-v` progress line
        # (`<nodeid> <OUTCOME> [pct]` — node-id is the tokens before the outcome) and
        # the summary line (`<OUTCOME> <nodeid> - <msg>` — node-id follows, up to a
        # lone `-`). The node-id's own brackets rejoin with spaces intact.
        oc_idx = next((i for i, t in enumerate(tokens) if t in _PYTEST_OUTCOMES), None)
        if oc_idx is None:
            continue
        outcome = tokens[oc_idx]
        if oc_idx == 0:
            rest = tokens[1:]
            nid = " ".join(rest[:rest.index("-")] if "-" in rest else rest)
        else:
            nid = " ".join(tokens[:oc_idx])
        if not nid:
            continue
        for n in node_set:
            # Exact node-id, or one of its parametrised variants (`node[param]`).
            if nid == n or nid.startswith(n + "["):
                if outcome == "PASSED":
                    passed_any.add(n)
                elif outcome in ("FAILED", "ERROR"):
                    bad_any.add(n)
                break  # a line attributes to exactly one base node
    return passed_any, bad_any


def _verify_nodes(node_ids, repo=None, tests_root=None,
                  deadline: float | None = None) -> dict[str, tuple[str, str]]:
    """One pytest invocation PER NODE under `verify.node_budget_seconds`
    (D-006), so a node that exceeds its budget can never mark a sibling
    not-passing — replacing the single batched run with its hardcoded
    `timeout=300` (F-102, the KLC-105 defect this ticket exists to close).
    Returns `{node_id: (state, reason)}` with `state` in
    `{pass, fail, unverified}` (`verify_runner.PASSED/FAILED/UNVERIFIED`).

    review-fix (HIGH, AC-10/AC-11/AC-12): *deadline* is a `time.monotonic()`
    value for the verification arm of one ack (KLC-174: this module is the only
    arm left; before it was shared with the removed replay arms) — created ONCE at the top of
    `can_complete_build` and threaded down — so the total ack ceiling is one
    `verify.arm_budget_seconds`, not one per call. A caller that has no shared
    deadline (a standalone/test call) still gets one computed here, same as
    before.
    """
    node_ids = list(dict.fromkeys(n for n in node_ids if n))
    if not node_ids:
        return {}
    collected = _collect_existing(node_ids, repo, tests_root)   # existence floor, unchanged
    cwd = None
    if repo is not None:
        cwd = str(repo)
    elif tests_root is not None:
        cwd = str(Path(tests_root).parent)
    budget = settings.verify_node_budget()
    if deadline is None:
        deadline = time.monotonic() + settings.verify_arm_budget()
    base = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider"]
    out: dict[str, tuple[str, str]] = {}
    for node in node_ids:
        if node not in collected:
            out[node] = (verify_runner.UNVERIFIED, "uncollected")   # weak, as today (D-201)
            continue
        if time.monotonic() >= deadline:
            out[node] = (verify_runner.UNVERIFIED, "arm-budget-exhausted")
            continue
        cmd = base + [node, "--tb=no", "-v"]
        v = verify_runner.run(cmd, budget_s=budget, cwd=cwd)
        if v.state == verify_runner.UNVERIFIED:
            reason = ("slow" if v.reason == verify_runner.BUDGET_EXCEEDED
                     else v.reason)                                # AC-11
            out[node] = (verify_runner.UNVERIFIED, reason)
            continue
        # The command ran. AC-19 keeps the RUNNER on exit status alone, but
        # pytest exits 0 for an all-skipped node, so the pytest-aware layer
        # (the one C-007 permits) attributes the real outcome from the -v
        # lines, through the SAME parser `_verify_passing` uses (D-201).
        passed, bad = _attribute_outcomes(v.output, [node])
        if node in bad:
            out[node] = (verify_runner.FAILED, "")
        elif node in passed:
            out[node] = (verify_runner.PASSED, "")
        else:
            out[node] = (verify_runner.UNVERIFIED, "skipped")      # F-1: never a pass
    return out


def _verify_passing(node_ids, repo=None, tests_root=None, deadline: float | None = None,
                    cache: dict | None = None) -> dict[str, bool]:
    """Confirm each node-id is collected AND passing, SCOPED to those node-ids.

    Boolean adapter kept for this module's own callers/tests (D-201): a
    skipped node lands `UNVERIFIED`, so this still returns `False` for it and
    `test_verify_passing_skip_is_not_passing` keeps asserting exactly what it
    asserts today, against the same parser. Degrade-not-fail: any
    pytest-invocation surprise degrades to `False` (never counted as passing).

    review-fix (HIGH, AC-10/AC-11/AC-12): when *cache* is given, it is
    populated (mutated in place) with the FULL `{node: (state, reason)}` map
    `_verify_nodes` computed — so a caller (`_evaluate`) that also needs the
    REASON for a not-passing node reads it from *cache* instead of calling
    `_verify_nodes` a second time, which would re-execute the same node via a
    second real pytest subprocess.
    """
    try:
        states = _verify_nodes(node_ids, repo, tests_root, deadline=deadline)
    except Exception:
        result = {n: False for n in dict.fromkeys(n for n in node_ids if n)}
        if cache is not None:
            cache.update({n: (verify_runner.UNVERIFIED, "runner-unavailable")
                         for n in result})
        return result
    if cache is not None:
        cache.update(states)
    return {n: (st == verify_runner.PASSED) for n, (st, _reason) in states.items()}


# ---------------------------------------------------------------------------
# Findings / Report and the track-scaled severity model.
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    ac_id: str
    state: str      # covered / drift / weak / miss / degraded
    severity: str   # BLOCK or SURFACE
    message: str
    deferred: bool = False


@dataclass
class Report:
    track: str
    findings: list[Finding] = field(default_factory=list)
    degraded: bool = False
    block_reason: str | None = None

    @property
    def surfaced(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SURFACE]


def _active(track: str) -> str:
    """Track = floor (C-004), mirroring `testplan_review._active_dimensions`:
    XS → skip, S → surface-only, M/L/unknown → block-on-miss."""
    t = (track or "").strip().upper()
    if t == "XS":
        return "skip"
    if t == "S":
        return "surface"
    return "block"  # M / L / unknown → block (fail-toward-more-review)


# --- ticket I/O seams (patchable in tests; degrade-not-fail) ----------------

def _ticket_dir(ticket: str) -> Path:
    try:
        from core.shared.paths import klc_ticket_meta_file
        return klc_ticket_meta_file(ticket).parent
    except Exception:
        return _project_root / ".klc" / "tickets" / ticket


def _load_texts(ticket: str) -> tuple[str, str]:
    d = _ticket_dir(ticket)

    def _rd(name: str) -> str:
        try:
            return (d / name).read_text(encoding="utf-8")
        except OSError:
            return ""

    return _rd("spec.md"), _rd("test-plan.md")


def _tests_root() -> Path:
    try:
        from core.shared.paths import project_root
        return project_root() / "tests"
    except Exception:
        return _project_root / "tests"


def _read_meta_ro(ticket: str) -> dict:
    """READ-ONLY track/override lookup — must not migrate meta on a probe (KLC-062)."""
    try:
        import lifecycle as _lc
        return _lc.read_meta_ro(ticket) or {}
    except Exception:
        return {}


# --- the ticket-level check -------------------------------------------------

def _degraded(report: Report, message: str) -> Report:
    report.degraded = True
    report.block_reason = None
    report.findings = [Finding("", "degraded", SURFACE, message)]
    return report


def _record(report: Report, mode: str, ac: str, state: str, deferred: bool,
            substantiated: bool = True) -> None:
    if state == MISS:
        if mode != "block":
            # S: surfaced, never blocks.
            report.findings.append(Finding(
                ac, MISS, SURFACE,
                f"{ac} has no implemented passing test — AC coverage miss (surfaced on S)"))
        elif deferred:
            report.findings.append(Finding(
                ac, MISS, SURFACE,
                f"{ac} has no implemented passing test "
                f"(deferred via meta.deferred_ac_coverage)", deferred=True))
        elif not substantiated:
            # The miss is NOT plan-substantiated: the plan declared no location for
            # this AC (so its only possible coverage is a git-discovered changed test,
            # which is additive and may be incomplete). Blocking here would let a git
            # condition force a MISS→block, so this SURFACES as undetermined instead.
            report.findings.append(Finding(
                ac, MISS, SURFACE,
                f"{ac} has no located test and the test-plan declared no coverage "
                f"location for it — AC coverage undetermined (git changed-files may "
                f"cover it), not blocking"))
        else:
            # Confident, plan-substantiated objective miss: the plan declared a real
            # location for this AC, that file was scanned, and it contains no
            # referencing test → block on M/L (git-independent basis).
            msg = (f"{ac} has no implemented passing test at its plan-declared "
                   f"location — objective AC coverage miss (blocks on M/L; set "
                   f"meta.deferred_ac_coverage to override)")
            report.findings.append(Finding(ac, MISS, BLOCK, msg))
            if report.block_reason is None:
                report.block_reason = msg
    elif state == DRIFT:
        report.findings.append(Finding(
            ac, DRIFT, SURFACE,
            f"{ac} is declared covered in the test-plan but no implemented passing "
            f"test references it — coverage drift"))
    elif state == WEAK:
        report.findings.append(Finding(
            ac, WEAK, SURFACE,
            f"{ac} has a referencing test that is a placeholder / uncollected / not "
            f"passing — weak coverage signal"))


def _path_allows(node_file: str, allowed: set[str]) -> bool:
    """True when *node_file* (a test file path from a node-id) is one of *allowed*
    (an AC's plan files ∪ the changed files), matching on the FULL path with a `/`-
    boundary suffix tolerance so differing project-relative spellings still match while
    nested monorepo files that only share a basename do NOT cross-match."""
    nf = node_file.replace("\\", "/")
    for p in allowed:
        pp = str(p).replace("\\", "/")
        if nf == pp:
            return True
        # Basename tolerance applies ONLY when one side is a BARE filename (no `/`) —
        # e.g. a plan cell that wrote `test_x.py` matches a project-relative
        # `tests/test_x.py`. It must NOT match two DIFFERENT multi-segment paths that
        # merely share a tail (`tests/test_api.py` vs `pkg_a/tests/test_api.py`), or a
        # stray test in another package's same-named file would falsely cover the AC.
        if "/" not in pp and nf.rsplit("/", 1)[-1] == pp:
            return True
        if "/" not in nf and pp.rsplit("/", 1)[-1] == nf:
            return True
    return False


def _evaluate(ticket, report, mode, spec_text, tp_text, repo, run_tests,
              deadline: float | None = None) -> Report:
    _acs = _saoc.parse_acs(spec_text)
    ac_ids = [ac.id for ac in _acs]
    # FIX-A (Codex P2, false-block): a malformed SAOC AC still parses via parse_acs, but
    # it is a spec-quality problem the spec self-check owns — it must NEVER drive an
    # AC-coverage block. Only well-formed ACs are block-eligible; malformed ones surface.
    _wellformed = {ac.id for ac in _acs if ac.is_wellformed}
    planned = _tpr.coverage_map(spec_text, tp_text)
    # Scope the scan to THIS ticket's own test files (plan locations + changed
    # tests) — never a repo-wide grep (FIX-1).
    candidates = _candidate_files(planned, repo)
    if not candidates:
        # Undetermined, NOT an objective miss: the test-plan declared no coverage
        # locations AND no changed test files were found, so the gate has no basis
        # to locate this ticket's tests. Blocking here would be a FALSE block (a
        # shallow clone + an empty coverage table must not block a genuinely-tested
        # M/L ticket). Degrade to a single SURFACE note — never block (no-false-block
        # invariant; the block is reserved for a locatable, objective miss).
        return _degraded(
            report,
            "cannot locate this ticket's test files (no plan-declared coverage "
            "locations and no changed test files) — AC coverage undetermined")
    # FIX (Codex P2): honor the repo override for a tests-root-relative plan location.
    # When `repo` is given, the tests root is `<repo>/tests`, not PROJECT_ROOT's — else
    # a bare `test_x.py` under the override repo is never resolved and its AC is
    # mis-scanned (drift/miss) despite the test existing there.
    _troot = (Path(repo) / "tests") if repo else _tests_root()
    implemented, scanned = _scan_tests_for_ac_ids(_troot, ac_ids, candidates, repo)
    all_nodes = [n for nodes in implemented.values() for n in nodes]

    # Passing verification runs ONLY on the real ack path (run_tests=True). A
    # read-only probe (run_tests=False: remind / gate_policy on every prompt) does
    # ONLY the static AC→file classification and spawns NO pytest (FIX-2): a probe
    # must never execute the ticket's tests. When tests aren't run, a referencing
    # test is taken at face value (covered); the ack path then confirms it passes.
    passing: dict[str, bool] = {}
    # review-fix (HIGH, AC-10/AC-11/AC-12): _node_states caches EVERY node's
    # (state, reason) from this ONE _verify_nodes invocation (inside
    # _verify_passing below) — the per-AC loop further down reads this cache
    # instead of calling _verify_nodes again, so a node shared by multiple ACs
    # is executed via a real pytest subprocess at most ONCE per ack, not once
    # per referencing AC.
    _node_states: dict[str, tuple[str, str]] = {}
    if run_tests and all_nodes:
        try:
            passing = _verify_passing(all_nodes, repo, _troot, deadline=deadline,
                                      cache=_node_states) or {}
        except Exception:
            passing = {}  # pytest surprise → nodes unconfirmed → degrade to WEAK/surface

    deferred = bool(_read_meta_ro(ticket).get("deferred_ac_coverage"))
    # FIX (Codex P2, false-COVERED): AC ids restart per ticket, so a `test_ac1` living
    # in a file declared for a DIFFERENT AC must NOT cover AC-1. An AC is covered only
    # by a referencing test in ITS OWN plan-declared files ∪ the ticket's changed test
    # files (new tests are additive and legitimately cover the AC they reference).
    # Match on the FULL project-relative path (suffix-tolerant), so nested monorepo
    # files that share a basename — pkg_a/tests/test_api.py vs pkg_b/tests/test_api.py —
    # are distinguished (a bare basename match would falsely cross them).
    _changed_paths = {p for p in (_changed_test_files(repo) or set())}
    for ac in ac_ids:
        if ac not in _wellformed:
            # Malformed SAOC AC → undetermined; surface, never block (FIX-A).
            report.findings.append(Finding(
                ac, MISS, SURFACE,
                f"{ac} is not well-formed SAOC — AC coverage undetermined "
                f"(spec self-check owns malformed ACs), not blocking"))
            continue
        ac_plan_files = _plan_files({ac: planned.get(ac, [])})
        _allowed_paths = set(ac_plan_files) | _changed_paths
        nodes = [n for n in implemented.get(ac, [])
                 if _path_allows(n.split("::", 1)[0], _allowed_paths)]
        if not run_tests:
            if nodes:
                continue  # covered (static classification, unchanged)
        else:
            if any(passing.get(n) for n in nodes):
                continue  # covered: a referencing test exists and genuinely passed
            if nodes:
                # KLC-115 D-201: re-probe only THIS AC's own not-passing nodes
                # for their REASON (bounded — never the whole ticket's node set
                # again, and never called at all when `passing` already found a
                # pass). A definite negative observation (a real fail, or a
                # definite skip/uncollected) is WEAK, exactly as today —
                # `skipped`/`uncollected` are NOT excusable, so a skip still
                # cannot evade the gate (F-104). Only when EVERY node's result
                # is inconclusive (the gate could not observe at all) is the AC
                # reported `unverified: <reason>` instead (AC-11) — never
                # silently dropped, and excluded from the weak/drift/miss
                # population that today's false-WEAK defect poisoned.
                #
                # review-fix (HIGH, AC-10/AC-11/AC-12): read the REASON from
                # `_node_states` — already computed once, above, for every
                # node in `all_nodes` — instead of calling `_verify_nodes`
                # again. A node shared by N acceptance criteria was previously
                # re-executed via a real pytest subprocess up to N+1 times.
                reasons = _node_states
                states = [reasons.get(n, (verify_runner.UNVERIFIED, "runner-unavailable"))
                         for n in nodes]
                definite_negative = any(
                    st == verify_runner.FAILED
                    or (st == verify_runner.UNVERIFIED and r not in _INCONCLUSIVE)
                    for st, r in states)
                if definite_negative:
                    _record(report, mode, ac, WEAK, deferred, False)
                else:
                    reason = next((r for st, r in states
                                  if st == verify_runner.UNVERIFIED), "runner-unavailable")
                    report.findings.append(Finding(
                        ac, UNVERIFIED, SURFACE,
                        f"{ac}: unverified: {reason} — the referencing test could "
                        f"not be observed, not a coverage miss"))
                continue
        # No referencing test in ANY candidate (plan OR git-changed). A BLOCK must be
        # SUBSTANTIATED by the plan alone (git is additive, never a block basis): at
        # least one of this AC's PLAN-declared files must have been successfully
        # scanned and found to contain no referencing test. If the plan declared a
        # location but its file is absent/unscannable → drift (surface); if the plan
        # declared nothing → undetermined (surface). Either way, never a block.
        # FIX-B (Codex P2, false-block): substantiate a MISS only when EVERY one of the
        # AC's plan-declared files was successfully scanned — the AC's referencing test
        # could live in a planned file that was missing/unscannable. A partial scan can
        # never prove absence, so it is DRIFT (surface), not a block.
        substantiated = bool(ac_plan_files) and ac_plan_files <= scanned
        if planned.get(ac) and not substantiated:
            _record(report, mode, ac, DRIFT, deferred, False)
        else:
            _record(report, mode, ac, MISS, deferred, substantiated)
    return report


def check(ticket: str, track: str, repo: Path | None = None, *,
          run_tests: bool = True, deadline: float | None = None) -> Report:
    """Run the AC→implemented-test coverage check for *ticket* at *track*.

    Track-scaled (C-004): XS skips, S surfaces, M/L block on an objective miss.
    Degrade-not-fail (C-003): a missing/malformed spec.md or test-plan.md, or any
    surprise, yields a single SURFACE note and never blocks or raises.

    *run_tests* gates the scoped pytest verification: the real ack path passes True;
    a read-only probe passes False so it does only the static classification and
    spawns no pytest (FIX-2 — a per-prompt probe must not execute the ticket's tests).

    *deadline* (review-fix, HIGH, AC-10/AC-11/AC-12): a `time.monotonic()` value
    for the verification arm of one ack (this module only since KLC-174) — passed down from `can_complete_build` so
    the total ack ceiling is one `verify.arm_budget_seconds`, not one per arm.
    `None` (the default, e.g. a standalone/test call) computes a fresh one.
    """
    report = Report(track=(track or "").strip().upper() or "?")
    if _active(track) == "skip":
        return report
    mode = _active(track)
    try:
        spec_text, tp_text = _load_texts(ticket)
    except Exception:
        return _degraded(report, "could not read spec.md/test-plan.md — AC coverage check degraded")

    try:
        acs = _saoc.parse_acs(spec_text or "")
    except Exception:
        acs = []
    if not acs:
        return _degraded(report,
                         "no SAOC acceptance criteria found in spec.md — AC coverage check degraded")
    if not (tp_text or "").strip():
        return _degraded(report, "test-plan.md is absent or empty — AC coverage check degraded")

    try:
        return _evaluate(ticket, report, mode, spec_text, tp_text, repo, run_tests,
                         deadline=deadline)
    except Exception as exc:  # defensive: a surprise never blocks the build ack
        return _degraded(report, f"AC coverage check degraded ({exc!r})")


def warn_lines(report: Report) -> list[str]:
    """Compact one-line-per-finding SURFACE advisories for the ack path."""
    out: list[str] = []
    for f in report.surfaced:
        tag = f.state + (":deferred" if f.deferred else "")
        out.append(f"ac-coverage[{tag}]: {f.message}")
    return out


# KLC-117 Q-003 severity table: weak/drift are info, a degraded run is medium
# (the check itself did not run, which is more consequential than one AC's
# state).
_SEVERITY = {"degraded": "medium"}


def advisory_records(report: Report) -> list[dict]:
    """The KLC-117 record form of `warn_lines`. Same conditions, same wording,
    a typed carrier. `warn_lines` stays for this module's own tests and CLI.

    A degraded report's synthetic Finding (`state="degraded"`, produced by
    `_degraded`) is already in `report.surfaced` — the severity table below
    picks it up through the same per-finding loop, no separate branch needed.
    """
    out: list[dict] = []
    for f in report.surfaced:
        tag = f.state + (":deferred" if f.deferred else "")
        out.append({"source": "ac-coverage",
                    "severity": _SEVERITY.get(f.state, "info"),
                    "code": f"ac-coverage.{tag}", "message": f.message,
                    "ref": f.ac_id})
    return out
