"""tests/integration/test_klc154_fidelity.py — KLC-154 step-7, external
review F-8 (LOW): the AC-9 cross-check compares the mapping with ITSELF
(the stored JSON, mapped once with `stamp=True`, against the `.md`
derived through the SAME `map_findings`), so it reliably catches a real
md/JSON content disagreement but CANNOT catch a mapping defect common to
both sides — a wrong title cut, a wrong file placeholder, and so on.

This test adds the independent fidelity check the external reviewer ran
by hand, over the WHOLE frozen corpus: for every old-shape record, every
old `category`/`detail`/`suggested_fix`/`severity`/`id`/`ac`/`line` value
is recoverable from its mapped record.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


def _old_candidates(tdir: Path):
    """Every `(kind, rel, position, old_record)` of *tdir*'s candidate
    files, BEFORE any migration — the same candidate list
    `support.snapshot_findings` walks."""
    out = []
    for rel in support._CANDIDATE_RELS:
        path = tdir / rel
        if not path.is_file():
            continue
        name = Path(rel).name
        if rel.endswith(".md"):
            kind = support._MD_KIND.get(name)
            if kind is None:
                continue
            span = findings_migrate._verdict_span(path.read_text(encoding="utf-8"))
            items = list(span[2].get("findings") or []) if span else []
        else:
            kind = support._JSON_KIND.get(name)
            if kind is None:
                continue
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                items = []
            if not isinstance(items, list):
                items = []
        for i, rec in enumerate(items, start=1):
            if isinstance(rec, dict) and findings_migrate.is_old(rec):
                out.append((kind, rel, i, rec))
    return out


def _assert_fidelity(old: dict, mapped: dict, where) -> None:
    assert str(old.get("severity", "")).upper() == mapped["severity"], where
    if any(k in old for k in ("category", "detail", "suggested_fix")):
        detail = str(old.get("detail", "")).strip()
        assert detail in mapped["body"], (where, "detail not recoverable from body")
        cat = old.get("category", "")
        same_rule = mapped["rule_name"] == cat
        legacy_prefixed = (mapped["rule_name"] == findings_migrate.findings.LEGACY_RULE_NAME
                           and f"[legacy category: {cat}]" in mapped["body"])
        assert same_rule or legacy_prefixed, (where, "category not recoverable")
        assert (old.get("suggested_fix") or None) == mapped["fix"], (where, "suggested_fix")
        if old.get("id"):
            assert mapped["id"] == old["id"], (where, "non-empty id not kept")
        assert str(old.get("ref", "")) == mapped["ref"], (where, "ref not kept verbatim")
    else:
        for key in ("file", "title", "body", "fix"):
            if key in old:
                assert old[key] == mapped[key], (where, key)
        if "ac" in old:
            assert old["ac"] == mapped.get("ac"), (where, "ac")
        line = old.get("line")
        expected_line = line if type(line) is int and line > 0 else None
        assert mapped["line"] == expected_line, (where, "line")


def test_every_old_value_is_recoverable_from_its_mapped_record(tmp_path):
    """F-8: run over the WHOLE frozen corpus (every ticket, every
    candidate file, every old-shape record) — not a sample."""
    tickets = tmp_path / "tickets"
    tickets.mkdir()
    keys = support.materialize_corpus(tickets)
    checked = 0
    for key in keys:
        tdir = tickets / key
        for kind, rel, position, old in _old_candidates(tdir):
            mapped = findings_migrate.map_finding(old, kind, position)
            _assert_fidelity(old, mapped, (key, rel, position))
            checked += 1
    assert checked > 0
