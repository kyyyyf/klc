"""tests/integration/test_klc154_fixtures.py — KLC-154 step-3, AC-13: the
frozen corpus holds at least 30 findings JSON files and 10 `.md` verdicts,
at least three instances of each of the five old shapes (spec.md's Data
shapes section), at least one real instance of each Q-103 legacy case, a
`README.md` naming each file's origin/shape/derivation, every corpus ticket
holding at least one old-shape file (so a lock victim always reaches the
lock, impl-plan-review F-4) — and the corpus directory stays flat (D-008).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


def test_corpus_composition_floor(tmp_path, monkeypatch):
    """AC-13: the floor counts, the five-shape coverage, the three Q-103
    legacy cases, the README, and that every ticket holds at least one
    old-shape file."""
    assert support.CORPUS.is_dir()
    files = [p for p in support.CORPUS.iterdir() if p.is_file() and p.name != "README.md"]
    json_files = [p for p in files if p.suffix == ".json"]
    md_files = [p for p in files if p.suffix == ".md"]
    assert len(json_files) >= 30
    assert len(md_files) >= 10

    shape1 = shape2 = shape3 = shape4 = shape5 = 0
    out_of_vocab = recommendation_key = line_zero = False

    for p in files:
        text = p.read_text(encoding="utf-8")
        _, _, relpath_enc = p.name.partition("__")
        basename = Path(relpath_enc.replace("--", "/")).name
        if p.suffix == ".json":
            data = json.loads(text)
            if data == []:
                shape4 += 1
                continue
            first = data[0]
            if "category" in first or "detail" in first:
                shape1 += 1
                kind = support._JSON_KIND.get(basename)
                rule_names = findings_migrate.handback.KINDS[kind].rule_names if kind else ()
                for rec in data:
                    if rec.get("category") not in (rule_names or ()):
                        out_of_vocab = True
            else:
                lines = [rec.get("line") for rec in data]
                if 0 in lines:
                    line_zero = True
                if all(ln is None for ln in lines):
                    shape3 += 1
                elif all(isinstance(ln, int) and ln and ln != 0 for ln in lines):
                    shape2 += 1
        else:
            shape5 += 1
            span = findings_migrate._verdict_span(text)
            assert span is not None, p
            for d in span[2].get("decisions_to_confirm") or []:
                if "recommendation" in d and "recommended" not in d:
                    recommendation_key = True

    assert shape1 >= 3, shape1
    assert shape2 >= 3, shape2
    assert shape3 >= 3, shape3
    assert shape4 >= 3, shape4
    assert shape5 >= 3, shape5
    assert out_of_vocab, "no out-of-vocabulary category found in the corpus"
    assert recommendation_key, "no 'recommendation'-not-'recommended' decision found"
    assert line_zero, "no in-client line: 0 record found"

    readme = (support.CORPUS / "README.md").read_text(encoding="utf-8")
    for p in files:
        assert p.name in readme, f"{p.name} is not named in README.md"

    tickets = support.make_project(tmp_path, monkeypatch)
    keys = support.materialize_corpus(tickets)
    assert len(keys) >= 20
    for key in keys:
        tdir = tickets / key
        found_old = False
        for rel in support._CANDIDATE_RELS:
            path = tdir / rel
            if path.is_file() and any(
                    findings_migrate.is_old(r) for r in support._findings_of(path)):
                found_old = True
                break
        assert found_old, f"{key} has no old-shape file (would never reach the lock)"


def test_corpus_directory_is_flat(tmp_path, monkeypatch):
    """D-008: the corpus directory holds no subdirectory (ignoring
    `__pycache__`), so it never becomes an extra index module."""
    for p in support.CORPUS.iterdir():
        if p.is_dir() and p.name != "__pycache__":
            raise AssertionError(f"{p} is a subdirectory of the corpus (must stay flat)")
