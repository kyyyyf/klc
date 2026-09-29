"""tests/shared/fresh_index.py — KLC-136 step-3: hermetic index/inventory
builders. Every function here derives its answer from a GIVEN tree (a tmp
mirror, or the real repo tree read only for its tracked-file LIST via `git
ls-files`, never via `PROJECT_ROOT`/`klc_index_dir()`), so the result is the
same whether the live `.klc/index/` is absent, stale or current.

`build_fresh_inventory(root)` is cheap (no subprocess pipeline) because
`deterministic_inventory.build_inventory` is already a pure function of
(root, ruleset, astgrep_path, files) — nothing in its call graph touches
`PROJECT_ROOT` when `files=` is passed explicitly (impl-plan.md step-3).

`build_fresh_index(root, mirror_dir)` is the expensive one (impl-plan-review
F-1): `dep_graph.py <root>` reads `<root>/.klc/index/structural.json`
directly, and starts `import-graph.py` with `PROJECT_ROOT=<root>` — so
running any builder with `root=framework_root()` (even with `PROJECT_ROOT`
pointed elsewhere) would read the LIVE index. Instead this copies the
TRACKED, working-tree content of `root` into `mirror_dir` (a real, separate
git repo), and runs every builder `scripts/update.py` uses, in the same
order, against THAT mirror — so `<root-arg>/.klc/index` for every builder
is the mirror's own, freshly-built output, and no path any builder can
default to lies under a live root.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILLS_DIR = _REPO_ROOT / "core" / "skills"
for _p in (str(_REPO_ROOT), str(_SKILLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import deterministic_inventory  # noqa: E402
import file_universe  # noqa: E402
import tools as _tools  # noqa: E402

_BUILD_TIMEOUT = 60
_DEP_GRAPH_TIMEOUT = 150  # dep_graph.py itself launches import-graph.py with a 120s cap


def build_fresh_inventory(root) -> dict:
    """AC-1: the symbol inventory of *root*, built from the current tree —
    never `REPO_ROOT/.klc/index/inventory.json`. `file_universe.resolve(root,
    structural={})` skips the `structural.json` read entirely
    (`core/skills/file_universe.py:60`: a non-None `structural` short-circuits
    the `structural_path` fallback), so this never touches ANY `.klc/index/`,
    live or stand-in."""
    root = Path(root)
    ruleset = deterministic_inventory.resolve_ruleset()
    universe = file_universe.resolve(root, structural={})["files"]
    astgrep = _tools.resolve_tool("ast-grep")
    return deterministic_inventory.build_inventory(
        root, ruleset, str(astgrep) if astgrep else None, files=universe)


def _tracked_files(root: Path) -> list[str]:
    r = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-c", "-z"],
        capture_output=True, timeout=30, check=True,
    )
    raw = r.stdout.decode("utf-8", errors="surrogateescape")
    return [p for p in raw.split("\0") if p]


def _mirror_tracked_files(root: Path, mirror_dir: Path) -> None:
    """Copies the tracked files of *root*, working-tree CONTENT (a build's
    uncommitted edits are what a test must see), into *mirror_dir*, then
    gives the mirror its own git repo so the builders' own `git ls-files`
    calls work. A missing tracked file (deleted but not yet staged) is
    skipped, never an error; an untracked directory (e.g. a local `jatdlc/`)
    is never copied at all, since it is not in the `ls-files` list.

    Review round 1 ext LOW: stages the EXACT tracked list with `git add -f`
    (reading it via `--pathspec-from-file=-`/`--pathspec-file-nul`, never as
    a giant argv, so this scales past any shell/ARG_MAX concern), instead of
    `git add -A` — a plain `-A` respects the freshly-copied `.gitignore`,
    so a file that is tracked AND gitignored (e.g. this repo's own
    `profiles/generic/mcp.json`) gets copied but never staged, and every
    builder that calls `git ls-files` in the mirror (`file_scanner.py`,
    `file_universe.py`) then silently disagrees with the real tree about
    that file's membership.
    """
    mirror_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for rel in _tracked_files(root):
        src = root / rel
        if not src.exists():
            continue
        dst = mirror_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst, follow_symlinks=True)
        copied.append(rel)
    subprocess.run(["git", "init", "-q"], cwd=str(mirror_dir), check=True, timeout=30)
    if copied:
        payload = ("\0".join(copied) + "\0").encode("utf-8", errors="surrogateescape")
        subprocess.run(
            ["git", "add", "-f", "--pathspec-from-file=-", "--pathspec-file-nul"],
            cwd=str(mirror_dir), input=payload, check=True, timeout=60,
        )


def _run(cmd: list[str], cwd: Path, env: dict, timeout: int = _BUILD_TIMEOUT):
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True,
                           text=True, timeout=timeout)


def _script(name: str) -> str:
    return str(_SKILLS_DIR / name)


def build_fresh_index(root, mirror_dir) -> Path:
    """AC-2's fixtures (step-4+): builds a full `.klc/index/` — structural,
    depgraph, modules, inventory, test_map, file_roles, module_edges,
    symbol_usage — into `<mirror_dir>/.klc/index`, by mirroring *root*'s
    tracked files into `mirror_dir` (D-216) and running every builder
    `scripts/update.py`/`scripts/init.py` use, in the same order, against
    the mirror. Returns the index directory."""
    root = Path(root)
    mirror_dir = Path(mirror_dir).resolve()
    _mirror_tracked_files(root, mirror_dir)

    index_dir = mirror_dir / ".klc" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PROJECT_ROOT": str(mirror_dir)}

    r = _run([sys.executable, _script("file_scanner.py"), str(mirror_dir)], mirror_dir, env)
    if r.returncode != 0:
        raise RuntimeError(f"fresh_index: file_scanner.py failed: {r.stderr}")
    (index_dir / "structural.json").write_text(r.stdout, encoding="utf-8")

    r = _run([sys.executable, _script("dep_graph.py"), str(mirror_dir)], mirror_dir, env,
              timeout=_DEP_GRAPH_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError(f"fresh_index: dep_graph.py failed: {r.stderr}")
    (index_dir / "depgraph.json").write_text(r.stdout, encoding="utf-8")

    for name, extra_args in (
        ("modules_build.py", ["--root", str(mirror_dir)]),
        ("deterministic_inventory.py", ["--root", str(mirror_dir)]),
        ("test_map.py", ["--root", str(mirror_dir)]),
        ("file_roles.py", ["--root", str(mirror_dir)]),
        ("module_edges.py", ["--edges-only"]),
        ("symbol_usage.py", []),
    ):
        r = _run([sys.executable, _script(name), *extra_args], mirror_dir, env)
        if r.returncode != 0:
            raise RuntimeError(f"fresh_index: {name} failed: {r.stderr}")

    return index_dir


def make_live_index_state(stand_in_dir, state: str, fresh_index_dir) -> None:
    """Writes the stand-in `PROJECT_ROOT` at `stand_in_dir` in one of three
    states: `absent` (no `index/` at all), `current` (a byte-for-byte copy
    of `fresh_index_dir`), or `stale` (a copy with every inventory symbol
    `line` shifted by +50 and the last `modules.json` module dropped)."""
    stand_in_dir = Path(stand_in_dir)
    stand_in_dir.mkdir(parents=True, exist_ok=True)
    if state == "absent":
        return
    if state not in ("current", "stale"):
        raise ValueError(f"unknown live_index_state: {state!r}")

    index_dir = stand_in_dir / ".klc" / "index"
    shutil.copytree(fresh_index_dir, index_dir)
    if state == "current":
        return

    inv_path = index_dir / "inventory.json"
    if inv_path.exists():
        data = json.loads(inv_path.read_text(encoding="utf-8"))
        for sym in data.get("symbols", []):
            if isinstance(sym.get("line"), int):
                sym["line"] += 50
        inv_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    mods_path = index_dir / "modules.json"
    if mods_path.exists():
        mdata = json.loads(mods_path.read_text(encoding="utf-8"))
        mods_list = mdata.get("modules") if isinstance(mdata, dict) else mdata
        if isinstance(mods_list, list) and mods_list:
            mods_list.pop()
        mods_path.write_text(
            json.dumps(mdata, indent=2, ensure_ascii=False), encoding="utf-8")
