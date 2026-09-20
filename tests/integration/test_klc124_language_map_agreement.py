"""KLC-124 — ONE canonical extension->language map.

`core/skills/file_scanner.py::EXT_LANG` is the single hand-authored
extension-to-language source of truth. `profiles/generic/sgconfig.yml`'s
ast-grep `languageGlobs` is a second, independently hand-authored table that
must agree with it on every extension they both name — a `.h` header used to
disagree (`EXT_LANG["h"] == "c"` vs. `languageGlobs.cpp` naming `**/*.h`),
which left a permanently-uncovered, phantom `c` language on every repo with
headers (raw.md).

This file grows across steps 1, 2, 4 and 8 (impl-plan.md); each test's own
docstring names the AC it proves. Step-8 (review round-2 MEDIUM #2)
replaced step-2's line-shape grep guard with an AST-based one — see the
"step-8" section below.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, FW_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ext_lang_h_maps_to_cpp():
    """AC-1: EXT_LANG["h"] resolves to "cpp", agreeing with
    profiles/generic/sgconfig.yml's languageGlobs.cpp entry for **/*.h."""
    fs = _load("fs_klc124_agree", "core/skills/file_scanner.py")
    assert fs.EXT_LANG["h"] == "cpp"


def test_ext_lang_and_sgconfig_agree_on_shared_extensions():
    """AC-2: for every extension profiles/generic/sgconfig.yml's
    languageGlobs names, EXT_LANG maps that exact same extension to that
    exact same language — a future edit reintroducing a disagreement must
    fail this test red."""
    import yaml  # local import (not module-level): re-resolves sys.modules['yaml']
    # at CALL time, after the suite-wide `_restore_real_pyyaml` autouse fixture
    # (tests/conftest.py) has repaired a shadow left by an earlier-collected
    # test — a module-level `import yaml` binds this name once at COLLECTION
    # time and stays stale for the rest of the process (same pattern as
    # tests/rule_test_executor.py's own documented fix).
    fs = _load("fs_klc124_agree2", "core/skills/file_scanner.py")
    sg = yaml.safe_load(
        (FW_ROOT / "profiles" / "generic" / "sgconfig.yml").read_text(encoding="utf-8"))
    assert fs.ext_lang_sgconfig_disagreements(sg["languageGlobs"]) == []


def test_agreement_check_tolerates_sgconfig_extension_ext_lang_lacks():
    """AC-3: an extension a profile's sgconfig.yml names that EXT_LANG has
    no entry for at all is NOT a disagreement — the guard bites only on a
    genuine value mismatch between two entries that both exist, never on a
    superset a custom profile legitimately adds."""
    fs = _load("fs_klc124_agree3", "core/skills/file_scanner.py")
    # "zz" is not an EXT_LANG key at all — a superset extension a future
    # profile adds must never be reported as a disagreement.
    assert fs.ext_lang_sgconfig_disagreements({"madeup": ["**/*.zz"]}) == []


# --- step-8: AST guard — no second hand-written extension->language table --
#
# Review round-2 MEDIUM #2: step-2's original grep guard required 3+
# CONSECUTIVE `"ext": "lang",` TEXT lines, which a single-line dict literal,
# a dict comprehension, single-quoted strings, or blank lines between
# entries all evade (verified experimentally). An AST walk is immune to all
# four: `ast.Dict`/`ast.DictComp` nodes carry their key/value pairs as
# parsed data, independent of how the source text is laid out or quoted.

_EXT_RE = re.compile(r"^[a-z0-9]{1,5}$")
_LANG_RE = re.compile(r"^[a-z][a-z0-9+#]*$")

# Files that legitimately import/derive from EXT_LANG rather than
# hand-authoring a second table — currently none, kept as an explicit
# extension point so a future derived view can be allowlisted by relative
# path instead of weakening the detector itself.
_ALLOWLISTED_DERIVED_VIEWS: frozenset[str] = frozenset()


def _str_const(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _entries_from_dict(node: ast.Dict):
    """Yield (key, value) string pairs from a `{...}` dict-literal's
    constant entries (skips `**`-unpacked or non-constant entries)."""
    for k, v in zip(node.keys, node.values):
        if k is None:  # a `**other` unpacking entry
            continue
        ks, vs = _str_const(k), _str_const(v)
        if ks is not None and vs is not None:
            yield ks, vs


def _entries_from_dictcomp(node: ast.DictComp):
    """Best-effort: recognizes a `{k: v for k, v in [(...), (...)]}` shape
    built from a literal list/tuple of 2-element constant-string tuples —
    the shape a hand-authored table would take as a comprehension. A
    comprehension over a non-literal source (a name, a call, a file read)
    is invisible here, same as it would be to any other static scan."""
    if not node.generators:
        return
    it = node.generators[0].iter
    if not isinstance(it, (ast.List, ast.Tuple)):
        return
    for elt in it.elts:
        if isinstance(elt, (ast.Tuple, ast.List)) and len(elt.elts) == 2:
            ks, vs = _str_const(elt.elts[0]), _str_const(elt.elts[1])
            if ks is not None and vs is not None:
                yield ks, vs


def _looks_like_ext_lang_entries(entries) -> bool:
    """True when 3+ entries each look like an extension->language pair: the
    key (dot stripped) matches an extension shape, the value matches a
    lowercase language-name shape."""
    count = 0
    for k, v in entries:
        key = k[1:] if k.startswith(".") else k
        if _EXT_RE.match(key) and _LANG_RE.match(v):
            count += 1
    return count >= 3


def _find_ext_lang_tables(path: Path):
    """AST-walk `path` for any dict literal or dict comprehension whose
    entries look like a second extension->language table. Yields
    `(lineno, kind)` per hit; a file that fails to parse yields nothing
    (this guard is a repo-hygiene check, not a syntax linter)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            if _looks_like_ext_lang_entries(_entries_from_dict(node)):
                yield node.lineno, "dict-literal"
        elif isinstance(node, ast.DictComp):
            if _looks_like_ext_lang_entries(_entries_from_dictcomp(node)):
                yield node.lineno, "dict-comprehension"


def _scan_for_second_tables(paths) -> dict[str, list]:
    """Scan `paths` (a `core/skills/*.py` + `scripts/*.py` iterable),
    excluding the canonical `file_scanner.py` and any allowlisted derived
    view, and return `{relative_path: [(lineno, kind), ...]}` for every
    file with at least one hit."""
    hits: dict[str, list] = {}
    for p in paths:
        if p.name == "file_scanner.py":
            continue
        rel = p.resolve().relative_to(FW_ROOT).as_posix()
        if rel in _ALLOWLISTED_DERIVED_VIEWS:
            continue
        found = list(_find_ext_lang_tables(p))
        if found:
            hits[rel] = found
    return hits


def test_no_second_extension_language_table_exists():
    """AC-4: no `core/skills/*.py` or `scripts/*.py` file other than
    `file_scanner.py` defines its own extension-to-language dict literal or
    dict comprehension — the "ONE data table" invariant raw.md requires.
    AST-based, so formatting (one line vs. many, quote style, blank lines
    between entries) cannot hide a second table from it."""
    paths = (sorted((FW_ROOT / "core" / "skills").glob("*.py"))
             + sorted((FW_ROOT / "scripts").glob("*.py")))
    hits = _scan_for_second_tables(paths)
    assert hits == {}, hits


def test_ast_guard_ignores_scattered_non_table_dict_entries(tmp_path):
    """Negative twin: extension/language-shaped key/value pairs that occur
    3+ times but scattered across SEPARATE small dict literals (never 3
    together in the same literal or comprehension) must not be flagged —
    mirrors `core/skills/elicitation.py`'s repeated `"topic": "scope"`-style
    question records, which are exactly this shape."""
    fake_module = tmp_path / "not_a_table.py"
    fake_module.write_text(
        'A = {"py": "python", "other": 1}\n'
        'B = {"rs": "rust", "other": 2}\n'
        'C = {"go": "golang", "other": 3}\n')
    assert list(_find_ext_lang_tables(fake_module)) == []


def test_ast_guard_bites_on_all_four_evading_second_table_shapes(tmp_path):
    """AC-4 (review round-2 MEDIUM #2): plant a second extension->language
    table in each of the four shapes verified to evade the old line-shape
    grep guard — a single-line dict literal, a dict comprehension, a
    single-quoted table, and a table with blank lines between entries — in
    a tmp copy, and confirm the AST guard reports every one."""
    shapes = {
        "evade_single_line.py":
            'FAKE = {"py": "python", "rs": "rust", "go": "golang"}\n',
        "evade_comprehension.py":
            'FAKE = {k: v for k, v in '
            '[("py", "python"), ("rs", "rust"), ("go", "golang")]}\n',
        "evade_single_quotes.py":
            "FAKE = {'py': 'python', 'rs': 'rust', 'go': 'golang'}\n",
        "evade_blank_lines.py":
            'FAKE = {\n'
            '    "py": "python",\n'
            '\n'
            '    "rs": "rust",\n'
            '\n'
            '    "go": "golang",\n'
            '}\n',
    }
    for name, source in shapes.items():
        p = tmp_path / name
        p.write_text(source)
        assert list(_find_ext_lang_tables(p)), f"{name} evaded the AST guard"


# --- step-4: tolerant readers keep loading an old index carrying 'c' -------

OLD_INVENTORY = {"errors": [
    {"builder": "inventory:c", "artifact": "inventory.json", "observed": 0,
     "universe": 2, "ratio": 0.0, "degraded": True},
    {"builder": "inventory:python", "artifact": "inventory.json", "observed": 10,
     "universe": 10, "ratio": 1.0, "degraded": False},
]}
OLD_STRUCTURAL = {"languages": {"c": {"files": 12, "lines": 140},
                                 "python": {"files": 10, "lines": 100}}}


def test_old_index_with_c_language_still_loads(tmp_path, monkeypatch):
    """AC-6: `index_coverage.inventory_language_verdicts`,
    `planning-retriever._candidate_languages` and `detect_languages.detect`
    each load an old-shape inventory.json/structural.json still carrying a
    `c` language key without raising and without any code path special-
    casing the literal string "c" — a pre-fix index keeps working unmodified
    after the upgrade."""
    ic = _load("ic_klc124", "core/skills/index_coverage.py")
    per_lang = ic.inventory_language_verdicts(OLD_INVENTORY)
    assert "c" in per_lang and per_lang["c"]["degraded"] is True

    pr = _load("pr_klc124", "core/skills/planning-retriever.py")
    # The OLD artifact's own 'c' entry is read as ordinary evidence, not
    # special-cased; the post-fix EXT_LANG maps a .h path to 'cpp' regardless
    # of what an old inventory.json happens to carry.
    langs = pr._candidate_languages({"legacy/widget.h": 1.0})
    assert langs == {"cpp"}

    dl = _load("dl_klc124", "core/skills/detect_languages.py")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    index_dir = tmp_path / ".klc" / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "structural.json").write_text(
        json.dumps(OLD_STRUCTURAL), encoding="utf-8")
    detected = dl.detect()
    assert "c" in detected  # >=10 files, exactly like any other language key
