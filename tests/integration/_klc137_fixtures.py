"""KLC-137 shared fixtures and view builders (step-2/step-4).

Not a test module — no `test_*` functions live here, so pytest never
collects it (D-111). Every inventory returned by `real_inventory` comes from
a REAL `build_inventory` run over a real fixture tree (C-005) — no test in
this ticket hand-shapes an inventory dict from scratch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import deterministic_inventory as di  # noqa: E402
import file_roles as _file_roles  # noqa: E402
import tools as _tools  # noqa: E402


def write_python_fixture(root: Path) -> Path:
    """F-003's four shapes, all reachable from ONE small module so a single
    `real_inventory()` call exercises every one:

    - a decorated function with a two-line signature (`f`) — `line` must stay
      on the `def` line, not the decorator's;
    - a class with a base and a method (`C`, `meth`);
    - a class-body assignment (`x = 1`);
    - a three-line dict assignment (`CONFIG`).

    Returns the file's path relative to *root* (posix-style, matching
    inventory.json's `file` field).
    """
    pkg = root / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    rel = "pkg/mod.py"
    (root / rel).write_text(
        '"""Fixture module for KLC-137 line_end tests."""\n'
        "\n"
        "\n"
        "def _dummy(fn):\n"
        "    return fn\n"
        "\n"
        "\n"
        "@_dummy\n"
        "def f(a,\n"
        "      b):\n"
        "    return a + b\n"
        "\n"
        "\n"
        "class C(Base):\n"
        "    x = 1\n"
        "\n"
        "    def meth(self):\n"
        "        return self.x\n"
        "\n"
        "\n"
        "CONFIG = {\n"
        '    "a": 1,\n'
        '    "b": 2,\n'
        "}\n",
        encoding="utf-8",
    )
    return Path(rel)


def _astgrep_path_or_skip() -> str:
    p = _tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def real_inventory(root: Path, astgrep: bool = True, ruleset: dict | None = None) -> dict:
    """A real `build_inventory()` output over *root* — the ast-grep path by
    default, the regex fallback when `astgrep=False`. *ruleset* overrides the
    profile-resolved ruleset (used by the C++/Rust hand-fixture tests, which
    scan a single language's rule dir rather than the active profile's)."""
    rs = ruleset if ruleset is not None else di.resolve_ruleset()
    astgrep_path = _astgrep_path_or_skip() if astgrep else None
    return di.build_inventory(root, rs, astgrep_path)


def strip_line_end(inv: dict) -> dict:
    """The true pre-KLC-137 shape: `line_end` entirely absent on every symbol
    (AC-4's / AC-7's 'old inventory', built before this ticket)."""
    out = json.loads(json.dumps(inv))
    for s in out.get("symbols", []):
        s.pop("line_end", None)
    return out


def null_line_end(inv: dict) -> dict:
    """`line_end` present but JSON `null` on every symbol — the AC-2
    regex-fallback shape, derived from a real ast-grep inventory so readers
    that do not care which producer emitted it can be exercised uniformly."""
    out = json.loads(json.dumps(inv))
    for s in out.get("symbols", []):
        s["line_end"] = None
    return out


# --------------------------------------------------------------------------- #
# step-4: retriever views
# --------------------------------------------------------------------------- #
_WIDE_FILLERS = (
    "quokka", "zeppelin", "xylophone", "yttrium", "umbrella", "vortex", "nimbus",
    "glacier", "tundra", "cobalt", "garnet", "jasper", "opal", "topaz", "amber",
    "onyx", "pearl", "coral", "slate", "denim", "khaki", "olive", "azure",
    "crimson", "maroon", "basalt", "cobweb", "driftwood", "ember",
)


def _write_base_tree(root: Path) -> None:
    """`pkg/widgets.py`: a class with a base and a method (both match the
    "widget" query, and the class is matched by BOTH `py-public-api` and
    `py-class-hierarchy` — the AC-5 dedup case), plus three more
    `widget_*` functions so the per-file cap (AC-6) has more than 3
    candidates to choose from, ordered deterministically by `start` (all
    five share the query's only matching token, "widget", so they tie on
    IDF weight — the cap's `start` tiebreak is what is under test).
    `pkg/other.py`: enters the slice only through its OWN docstring keyword
    ("widget"), never through a symbol name — AC-5's "keyword-only, no
    entry" case."""
    pkg = root / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "widgets.py").write_text(
        '"""Widget rendering helpers."""\n'
        "\n\n"
        "class WidgetBuilder(Base):\n"
        "    def build_widget(self):\n"
        "        return None\n"
        "\n\n"
        "def widget_alpha():\n"
        "    return 1\n"
        "\n\n"
        "def widget_beta():\n"
        "    return 2\n"
        "\n\n"
        "def widget_gamma():\n"
        "    return 3\n",
        encoding="utf-8",
    )
    (pkg / "other.py").write_text(
        '"""Handles widget configuration."""\n'
        "\n\n"
        "def helper_unrelated():\n"
        "    return 1\n",
        encoding="utf-8",
    )


def _write_wide25_tree(root: Path) -> None:
    """`pkg2/wide.py`: 30 symbols — 29 filler functions named after distinct
    words that appear NOWHERE else in this corpus (so each gets the HIGH,
    single-document IDF weight and fills the `_SYMBOL_SIGNAL_CAP` of 25),
    plus one `widget` function whose only token ("widget") is shared with
    `pkg2/other_wide.py`'s own purpose line — giving it the LOWEST weight in
    the corpus, so it never makes the cap (AC-5's "a file with more than 25
    symbols" case). `pkg2/other_wide.py` exists only to give "widget" that
    second document (so its IDF is genuinely lower, not merely untested) and
    to make the module's `files_likely_to_edit` slot non-empty."""
    pkg = root / "pkg2"
    pkg.mkdir(parents=True, exist_ok=True)
    lines = ['"""Wide widget catalogue for KLC-137 AC-5 cap test."""', "", ""]
    for name in _WIDE_FILLERS:
        lines += [f"def {name}():", "    return 1", "", ""]
    lines += ["def widget():", "    return 42"]
    (pkg / "wide.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (pkg / "other_wide.py").write_text(
        '"""Uses a widget somewhere."""\n'
        "\n\n"
        "def something_else():\n"
        "    return 1\n",
        encoding="utf-8",
    )


def _write_weighted_tree(root: Path) -> None:
    """KLC-137 step-7 review-fix (AC-6, code-review/external MEDIUM):
    `pkg3/mod.py` has 5 query-matching symbols whose best-matching tokens
    carry GENUINELY DIFFERENT IDF weights, not the "base" tree's all-tied
    case. `rare_gizmo_widget`'s own token "gizmo" is unique to this file
    (never repeated in `pkg3/other.py`, so it keeps the corpus's high,
    single-document weight), while every other candidate matches only
    through "widget" (shared with `other.py`'s purpose line, so it has the
    corpus's LOWEST weight) — so a query of "widget gizmo" makes
    `rare_gizmo_widget` the highest-weighted candidate despite being placed
    LAST (`start`=17, latest of the five) — a real, non-tiebreak-driven
    proof that the primary sort key is IDF weight descending, not `start`."""
    pkg = root / "pkg3"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "mod.py").write_text(
        '"""Weighted ordering fixture for KLC-137 review-fix step-7."""\n'
        "\n\n"
        "class WidgetBuilder(Base):\n"
        "    def build_widget(self):\n"
        "        return None\n"
        "\n\n"
        "def widget_alpha():\n"
        "    return 1\n"
        "\n\n"
        "def widget_beta():\n"
        "    return 2\n"
        "\n\n"
        "def rare_gizmo_widget():\n"
        "    return 3\n",
        encoding="utf-8",
    )
    (pkg / "other.py").write_text(
        '"""Handles widget configuration."""\n'
        "\n\n"
        "def helper_unrelated():\n"
        "    return 1\n",
        encoding="utf-8",
    )


_TREES = {
    "base": (_write_base_tree, "pkg"),
    "wide25": (_write_wide25_tree, "pkg2"),
    "weighted": (_write_weighted_tree, "pkg3"),
}


def retriever_views(tmp_path: Path, source: str = "base"):
    """A real, small multi-module tree (`source` selects the layout — "base"
    or "wide25", see the writers above) run through the real
    `build_inventory` + `file_roles.build_file_roles` pipeline (C-005 — no
    hand-shaped file_roles/inventory). Returns
    `(modules, file_roles, module_edges, test_map, inventory, token_idf)`
    with one `module_edges` entry so that view is never degraded."""
    writer, module_name = _TREES[source]
    root = tmp_path / f"src-{source}"
    writer(root)
    inv = real_inventory(root, astgrep=True)
    assert inv["symbols"], f"{source} fixture must yield at least one symbol"

    modules = {"modules": [
        {"name": module_name, "path": f"{module_name}/",
         "summary": f"{module_name} fixture module.", "keywords": []},
    ]}
    source_texts = {}
    for s in inv["symbols"]:
        f = s["file"]
        if f not in source_texts:
            source_texts[f] = (root / f).read_bytes()[:4096].decode(
                "utf-8", errors="ignore")
    fr = _file_roles.build_file_roles(inv, modules, {}, source_texts=source_texts)

    module_edges = {
        "edges": [{"from": module_name, "to": module_name,
                   "edge_types": ["dependency"], "confidence": "low",
                   "expand_by_default": False}],
        "errors": [], "notes": [],
    }
    test_map = {"modules": {}, "errors": [], "notes": []}
    return modules, fr, module_edges, test_map, inv, fr["token_idf"]
