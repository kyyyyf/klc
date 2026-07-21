"""KLC-074 — planning-index cut-over GATE (archive-wide scope-shift bound).

The module SET moved from the LLM `decompose` agent (file-stem modules, chosen by a
non-reproducible semantic judgement) to the deterministic `modules_build.py`
(directory-level clustering of the full tracked-file listing). Switching membership
shifts the `affected_modules` computed for EVERY ticket, so this gate proves — over the
REAL archive, not a synthetic fixture — that the shift stays within a justified,
directory-spine bound, and FAILS if a future `modules_build` change silently moves a
file's membership beyond it.

The GATE runs the LIVE `modules_build` over the actual KLC repo (real substrate) and
checks two invariants for every archived-ticket changed file that still exists in the
tree, against the frozen cut-over baseline (`tests/fixtures/klc074_cutover_baseline.json`
— which captured the OLD LLM resolution per file so a fresh checkout, which has no
`.klc/`, can still run the gate):

  1. NO NEW ORPHANS — every file the OLD (LLM) set assigned to a module MUST still
     resolve to a module under the LIVE deterministic set. Coverage never regresses;
     a change that orphaned, say, every `core/agents/*.md` file would fail here.

  2. DIRECTORY-SPINE CONTAINMENT — a file's LIVE module path and its frozen OLD module
     path must be in a prefix (containment) relationship: membership may only move UP
     (coarsen to an ancestor directory, e.g. `core/skills/scope_delta` → `core/skills`)
     or DOWN (refine to a descendant, e.g. `tests` → `tests/integration`) the SAME
     directory spine, never SIDEWAYS to an unrelated module. The repo-root module `.`
     is treated as the universal ancestor. A change moving `core/skills/scope_delta.py`
     into `core/phases` would fail here.

These invariants ARE the justified bound. The cut-over was accepted because the measured
shift over the whole archive satisfied them with zero violations (see the KLC-074 design
artifact for the per-ticket old→new numbers).
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
_SKILLS = REPO / "core" / "skills"
sys.path.insert(0, str(_SKILLS))
import modules_build as mb  # noqa: E402
import module_membership as mm  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "klc074_cutover_baseline.json"


def _baseline() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _live_module_set() -> dict:
    """Build modules_build over the LIVE repo, exactly as the wired pipeline does.
    Uses the authoritative git-tracked file universe (KLC-074 review HIGH-1/HIGH-2),
    so the gate exercises the same universe the pipeline would."""
    all_files, _ = mb.module_file_universe(REPO)
    return mb.build_modules({"entry_points": []}, None, all_files=all_files)


def _git_tracked_set() -> set:
    import subprocess
    r = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"],
                       capture_output=True, text=True)
    return {p for p in r.stdout.split("\0") if p}


def _norm(p: str) -> str:
    return (p or "").rstrip("/")


def _prefix_related(a: str, b: str) -> bool:
    """True iff paths a and b are in a containment relationship (one is an ancestor
    of, or equal to, the other). The repo-root '.' contains every path."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == "." or b == ".":
        return True
    return a == b or (b + "/").startswith(a + "/") or (a + "/").startswith(b + "/")


def _live_path(name, live) -> str:
    for m in live.get("modules", []):
        if m.get("name") == name:
            return m.get("path") or ""
    return ""


def test_fixture_present_and_populated():
    """The frozen archive corpus must exist and be non-trivial (guards against a gate
    that silently passes because the fixture is empty)."""
    bl = _baseline()
    assert bl["files"], "baseline froze no files"
    assert len(bl["tickets"]) >= 40, "baseline corpus unexpectedly small"


def test_no_covered_file_becomes_orphan():
    """Bound (1): every file the OLD LLM set covered still resolves under the LIVE
    deterministic set. Zero new orphans — coverage must not regress."""
    bl = _baseline()
    live = _live_module_set()
    regressions = []
    for path, rec in sorted(bl["files"].items()):
        if not (REPO / path).exists():
            continue  # file deleted since cut-over — modules_build cannot see it
        res = mm.file_to_module(path, live)
        if res["resolution_source"] == "orphan":
            regressions.append((path, rec["old_module"]))
    assert not regressions, (
        f"{len(regressions)} file(s) the LLM set covered now orphan under "
        f"modules_build (coverage regression): {regressions[:20]}")


def test_membership_moves_only_along_directory_spine():
    """Bound (2): every file's LIVE module path is prefix-related to its frozen OLD
    module path — coarsen/refine along the same spine, never a sideways reassignment."""
    bl = _baseline()
    live = _live_module_set()
    sideways = []
    same = coarser = finer = 0
    for path, rec in sorted(bl["files"].items()):
        if not (REPO / path).exists():
            continue
        res = mm.file_to_module(path, live)
        if res["resolution_source"] == "orphan" or res["primary_module"] is None:
            continue  # orphan regressions are covered by the other test
        old_path = _norm(rec["old_path"])
        new_path = _norm(_live_path(res["primary_module"], live))
        if not _prefix_related(old_path, new_path):
            sideways.append((path, rec["old_module"], old_path,
                             res["primary_module"], new_path))
            continue
        if old_path == new_path or old_path == "." and new_path == ".":
            same += 1
        elif new_path == "." or (old_path + "/").startswith(new_path + "/"):
            coarser += 1
        else:
            finer += 1
    assert not sideways, (
        f"{len(sideways)} file(s) moved SIDEWAYS to an unrelated module "
        f"(bound violated): {sideways[:20]}")
    # sanity: the corpus actually exercised the spine (non-degenerate gate)
    assert same + coarser + finer >= 100, (same, coarser, finer)


def test_live_module_set_is_directory_level_and_reproducible():
    """The LIVE build is directory-level (no LLM file-stem modules like
    `core/skills/scope_delta`) and byte-reproducible."""
    live = _live_module_set()
    a = json.dumps(_live_module_set(), sort_keys=True)
    b = json.dumps(live, sort_keys=True)
    assert a == b, "modules_build is not byte-reproducible over the live repo"
    # every module path is a directory (trailing slash) or the root sentinel '.'
    for m in live["modules"]:
        p = m["path"]
        assert p == "." or p.endswith("/"), f"non-directory module path: {p!r}"


def test_no_module_built_from_untracked_files():
    """KLC-074 review LOW-2 (+ HIGH-1 guard): every file in every LIVE module must be
    git-tracked, and the module count must stay in a sane band vs the frozen baseline.
    A future build bug that let untracked working-tree junk (or a mis-scoped walk)
    inflate the module SET fails here, even though it touches no baseline file."""
    live = _live_module_set()
    tracked = _git_tracked_set()
    leaked = []
    for m in live["modules"]:
        for f in m.get("files", []):
            if f not in tracked:
                leaked.append((m["name"], f))
    assert not leaked, f"module(s) built from untracked files: {leaked[:20]}"
    # module-count band: baseline froze 41 dir-level modules; allow growth/shrink but
    # catch runaway inflation (a phantom-module bug) or collapse.
    n = len(live["modules"])
    assert 25 <= n <= 70, f"live module count {n} outside the sane band [25,70]"
