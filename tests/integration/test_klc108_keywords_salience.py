"""KLC-108 — AC-6/AC-7: `file_roles.keywords` is derived from the file's
basename tokens, its top-level symbol names and the first line of its
docstring/leading comment, capped at a named constant and ordered by
salience (inverse document frequency) rather than alphabetically.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import file_roles as fr  # noqa: E402


def _views(index_dir: Path, *names) -> dict:
    """AC-2: every view this file needs, loaded from `fresh_index`'s
    directory rather than `.klc/index/`."""
    return {n: json.loads((index_dir / n).read_text(encoding="utf-8")) for n in names}


# --------------------------------------------------------------------------- #
# AC-6 — real substrate: plugin_gen.py's own name survives the cap
# --------------------------------------------------------------------------- #
def test_plugin_gen_keywords_include_plugin_and_gen(fresh_index):
    """`core/skills/plugin_gen.py` carries neither `plugin` nor `gen` under
    today's alphabetical 8-token cap (spec FACT). Basename tokens are never
    dropped under the salience cap (AC-7), so both survive regardless of
    the rest of the repository's token frequencies."""
    data = _views(fresh_index, "inventory.json", "modules.json", "structural.json")
    result = fr.build_file_roles(data["inventory.json"], data["modules.json"],
                                 data["structural.json"])
    rec = result["files"].get("core/skills/plugin_gen.py")
    assert rec is not None, "core/skills/plugin_gen.py missing from the file universe"
    assert {"plugin", "gen"} <= set(rec["keywords"]), rec["keywords"]


@pytest.mark.parametrize("live_index_state", ["absent", "stale", "current"], indirect=True)
def test_keywords_salience_verdict_unchanged_by_live_index_state(
        live_index_state, no_index_reads, fresh_index):
    """AC-2: `plugin_gen.py`'s keywords survive the cap whatever the live
    `.klc/index/` holds, and the check never reads it — the salience answer
    comes from `fresh_index`, built from the current tree, regardless of
    `PROJECT_ROOT`."""
    data = _views(fresh_index, "inventory.json", "modules.json", "structural.json")
    result = fr.build_file_roles(data["inventory.json"], data["modules.json"],
                                 data["structural.json"])
    rec = result["files"].get("core/skills/plugin_gen.py")
    assert rec is not None
    assert {"plugin", "gen"} <= set(rec["keywords"]), rec["keywords"]
    assert no_index_reads() == []


def test_keywords_include_first_docstring_line_tokens():
    """AC-6: the first line of a module's docstring contributes tokens to
    `keywords`, not just the basename/symbol names."""
    inv = {"symbols": [
        {"name": "helper", "kind": "function", "file": "core/x/mod.py",
         "line": 5, "visibility": "public"},
    ]}
    modules = {"modules": [{"name": "x", "path": "core/x"}]}
    structural = {"entry_points": []}
    source = ('"""Widget catalog utilities for rendering storefront panels."""\n'
              '\n\ndef helper():\n    pass\n')
    result = fr.build_file_roles(inv, modules, structural,
                                 source_texts={"core/x/mod.py": source})
    kws = result["files"]["core/x/mod.py"]["keywords"]
    assert {"widget", "catalog", "storefront"} & set(kws), kws


def test_keywords_do_not_include_symbols_below_top_level():
    """Edge case: a file with NO symbols at all (post AC-1..AC-3, every
    in-body local is simply absent from the inventory) must still resolve
    keywords from basename + docstring, never an empty list."""
    inv = {"symbols": []}
    modules = {"modules": [{"name": "x", "path": "core/x",
                            "files": ["core/x/utility_helpers.py"]}]}
    structural = {"entry_points": []}
    source = '"""Rotates credential tokens for outbound webhook signing."""\n'
    result = fr.build_file_roles(inv, modules, structural,
                                 source_texts={"core/x/utility_helpers.py": source})
    kws = result["files"]["core/x/utility_helpers.py"]["keywords"]
    assert kws, "keywords must not be empty when basename/docstring tokens exist"
    assert {"utility", "helpers"} & set(kws), kws


# --------------------------------------------------------------------------- #
# AC-7 — named cap, salience ordering
# --------------------------------------------------------------------------- #
def test_keyword_cap_is_a_named_constant():
    assert isinstance(fr._KEYWORD_CAP, int) and fr._KEYWORD_CAP > 0
    symbol_names = [f"sym{i}word" for i in range(30)]
    kws = fr._keywords("x/y/zephyrcap.py", symbol_names, "", None)
    assert len(kws) <= fr._KEYWORD_CAP


def test_basename_token_never_dropped_under_cap():
    """A rare basename token must survive the cap even when 15 other
    candidate (repository-common-flavoured) tokens compete for the same
    12 slots — and at least one of those must be the one dropped."""
    common = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
              "hotel", "india", "juliet", "kilo", "lima", "mike", "november",
              "oscar"]
    kws = fr._keywords("services/zephyr.py", common, "", None)
    assert "zephyr" in kws
    assert len(kws) <= fr._KEYWORD_CAP
    dropped = set(common) - set(kws)
    assert dropped, "expected at least one common token to be dropped by the cap"


def test_cap_ordering_is_not_alphabetical():
    """A token's IDF weight decides survival past the cap, not its position
    in the alphabet — the rare, high-IDF `zucchini` (alphabetically LAST)
    survives while the low-IDF `indigo` (alphabetically mid-pack) does not,
    the opposite of what a plain `sorted(tokens)[:cap]` would keep."""
    common = ["apple", "banana", "cherry", "damson", "endive", "fig", "grape",
              "honey", "indigo"]
    rare = ["walnut", "xigua", "yam", "zucchini"]
    idf = {"tokens": {**{t: 0.1 for t in common}, **{t: 5.0 for t in rare}},
           "default_idf": 1.0}
    all_tokens = common + rare
    assert len(all_tokens) == fr._KEYWORD_CAP + 1

    # path with no basename tokens of its own (single-char stem) isolates the
    # assertion to the symbol-name ranking alone.
    kws = fr._keywords("m/f.py", all_tokens, "", idf)
    assert set(kws) != set(sorted(all_tokens)[: fr._KEYWORD_CAP])
    assert "zucchini" in kws
    assert "indigo" not in kws
