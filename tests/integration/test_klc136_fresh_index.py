"""KLC-136 step-3 — fail-closed builder tests (impl-plan-review F-1):
`fresh_index.build_fresh_inventory`/`build_fresh_index` themselves must never
read the live (or a stand-in) `.klc/index/`, in process or in any builder
subprocess they launch. Real-substrate: these run the REAL builder pipeline
against the REAL repository tree, not a mocked one — only the destination
(a tmp mirror) and the read-tracking are test infrastructure.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests" / "shared"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "integration"))

import fresh_index as fresh_index_mod  # noqa: E402
from _klc137_fixtures import null_line_end, real_inventory, write_python_fixture  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
    )
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr or r.stdout}"


@pytest.mark.parametrize("live_index_state", ["current"], indirect=True)
def test_fresh_inventory_build_reads_no_live_index(live_index_state, no_index_reads):
    """AC-1: `build_fresh_inventory(REPO_ROOT)` records zero reads under the
    stand-in's `.klc/index` or `framework_root()/.klc/index`."""
    inv = fresh_index_mod.build_fresh_inventory(REPO_ROOT)
    assert inv["symbols"], "the fresh inventory must not be empty"
    assert no_index_reads() == []


@pytest.mark.parametrize("live_index_state", ["current"], indirect=True)
def test_fresh_index_build_reads_no_live_index(live_index_state, no_index_reads, tmp_path):
    """AC-2: `build_fresh_index(REPO_ROOT, mirror)` records zero reads under
    the stand-in's `.klc/index` or `framework_root()/.klc/index`, in process
    or in any builder subprocess, AND its `depgraph.json` carries a `python`
    import graph — proving `dep_graph.py` read the tmp mirror's OWN
    `structural.json` (not an absent one: a builder that silently degraded
    to "no import graph at all" would also record zero reads, so the
    positive assertion is what rules that out, impl-plan-review F-1)."""
    mirror = tmp_path / "mirror"
    index_dir = fresh_index_mod.build_fresh_index(REPO_ROOT, mirror)
    depgraph = json.loads((index_dir / "depgraph.json").read_text(encoding="utf-8"))
    assert "python" in depgraph.get("import_graphs", {}), depgraph.get("errors")
    assert no_index_reads() == []


def test_mirror_stages_tracked_but_gitignored_files(tmp_path):
    """AC-2, review round 1 ext LOW: a file that is tracked AND matched by
    `.gitignore` (e.g. this repo's own `profiles/generic/mcp.json`) must
    still be staged in the mirror — `git add -A` respects the copied
    `.gitignore` and silently drops it, so a builder that uses
    `git ls-files` in the mirror (`file_scanner.py`, `file_universe.py`)
    never sees it there, disagreeing with the real tree's own membership."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "t@example.com")
    _git(src, "config", "user.name", "T")
    _git(src, "config", "commit.gpgsign", "false")
    (src / ".gitignore").write_text("ignored_but_tracked.txt\n", encoding="utf-8")
    (src / "ignored_but_tracked.txt").write_text("keep me\n", encoding="utf-8")
    (src / "normal.txt").write_text("normal\n", encoding="utf-8")
    _git(src, "add", "-f", ".gitignore", "ignored_but_tracked.txt", "normal.txt")
    _git(src, "commit", "-q", "-m", "seed")

    mirror = tmp_path / "mirror"
    fresh_index_mod._mirror_tracked_files(src, mirror)

    assert (mirror / "ignored_but_tracked.txt").exists()
    r = subprocess.run(["git", "-C", str(mirror), "ls-files"],
                       capture_output=True, text=True, check=True)
    tracked_in_mirror = set(r.stdout.split())
    assert "ignored_but_tracked.txt" in tracked_in_mirror, tracked_in_mirror
    assert "normal.txt" in tracked_in_mirror
    assert ".gitignore" in tracked_in_mirror


def _minimal_modules_json() -> dict:
    return {"modules": [{"name": "pkg", "path": "pkg/", "files": []}], "cycles": [], "notes": []}


def _stub_fresh_index_dir(tmp_path: Path, inv: dict) -> Path:
    """A tmp `.klc/index`-shaped directory carrying only `inventory.json` +
    a minimal `modules.json` — the two files `make_live_index_state` reads
    (KLC-137 step-3 RED: called directly, not through the session `fresh_index`
    fixture, hermetic_project_root)."""
    src = tmp_path / "stub-index"
    src.mkdir(parents=True)
    (src / "inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    (src / "modules.json").write_text(json.dumps(_minimal_modules_json()), encoding="utf-8")
    return src


def test_stale_state_shifts_line_end_by_fifty_when_integer(tmp_path, hermetic_project_root):
    """KLC-137 AC-10: `make_live_index_state(..., "stale")` shifts an integer
    `line_end` by the same +50 as `line`, so `line_end >= line` is preserved
    (never an inverted range, F-012)."""
    fixture_root = tmp_path / "fixture-src"
    write_python_fixture(fixture_root)
    inv = real_inventory(fixture_root, astgrep=True)
    before = {(s["file"], s["name"]): (s["line"], s["line_end"]) for s in inv["symbols"]}
    assert any(isinstance(v[1], int) for v in before.values()), (
        "fixture must yield at least one real int line_end")

    stub_dir = _stub_fresh_index_dir(tmp_path, inv)
    stand_in = tmp_path / "stand-in"
    fresh_index_mod.make_live_index_state(stand_in, "stale", stub_dir)

    shifted = json.loads((stand_in / ".klc" / "index" / "inventory.json").read_text(encoding="utf-8"))
    for sym in shifted["symbols"]:
        orig_line, orig_end = before[(sym["file"], sym["name"])]
        assert sym["line"] == orig_line + 50
        if isinstance(orig_end, int):
            assert sym["line_end"] == orig_end + 50
        else:
            assert sym["line_end"] is None
        assert sym["line_end"] is None or sym["line_end"] >= sym["line"]


def test_stale_state_leaves_null_line_end_untouched(tmp_path, hermetic_project_root):
    """KLC-137 AC-10, F-012 edge case: a symbol whose `line_end` is `null`
    (the AC-2 regex-fallback shape) is left as `null` after the stale shift
    — no `TypeError` from `null + 50`, no fabricated int. Pin: guards a
    `None + 50` crash rather than exercising a genuinely new branch."""
    fixture_root = tmp_path / "fixture-src"
    write_python_fixture(fixture_root)
    inv = null_line_end(real_inventory(fixture_root, astgrep=True))
    assert inv["symbols"], "fixture must yield at least one symbol"
    assert all(s["line_end"] is None for s in inv["symbols"])

    stub_dir = _stub_fresh_index_dir(tmp_path, inv)
    stand_in = tmp_path / "stand-in"
    fresh_index_mod.make_live_index_state(stand_in, "stale", stub_dir)

    shifted = json.loads((stand_in / ".klc" / "index" / "inventory.json").read_text(encoding="utf-8"))
    assert shifted["symbols"], "shifted inventory must not be empty"
    for sym in shifted["symbols"]:
        assert sym["line_end"] is None
