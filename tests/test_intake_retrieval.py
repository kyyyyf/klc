"""KLC-073 — intake wires the deterministic planning retriever.

Two things are proven here:

1. **Intake → trace wiring.** `klc intake` builds
   `.klc/tickets/<KEY>/retrieval_trace.json` deterministically from the ticket
   description; it degrades to `status:"unavailable"` (exit 0) when the planning
   views are absent and NEVER writes `meta.affected_modules` (authority stays
   discovery/operator-owned — planning_indexer.md §Authority).
2. **Prompt cascade accuracy.** The discovery/design/review/test-planner prompts
   consume the trace and reference ONLY fields that the retriever actually emits
   (no reference to a nonexistent field).

Offline, deterministic, no network / LLM. Isolated in a throwaway PROJECT_ROOT.

Run with pytest, or standalone: `python3 tests/test_intake_retrieval.py`.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_FW / "core" / "phases"))
import intake  # noqa: E402

_AGENTS = _FW / "core" / "agents"
_RETRIEVER = _FW / "core" / "skills" / "planning-retriever.py"

# --------------------------------------------------------------------------- #
# fixture planning views (real frozen schemas; enough for a status:"ok" trace)
# --------------------------------------------------------------------------- #
_MODULES = {
    "modules": [
        {"name": "intake", "path": "core/intake/",
         "summary": "Parses and validates incoming ticket descriptions.",
         "keywords": ["ticket", "intake", "validation", "parse"]},
        {"name": "routing", "path": "core/routing/",
         "summary": "Routes requests to the right handler.",
         "keywords": ["route", "dispatch"]},
    ],
}
_FILE_ROLES = {
    "files": {
        "core/intake/validation.py": {
            "module_name": "intake",
            "roles": ["public_surface", "domain_logic"],
            "is_test": False, "is_generated": False, "is_config": False,
            "eligible_as_primary": True,
            "keywords": ["validate", "ticket", "schema"],
            "symbols": ["validate_ticket"]},
        "core/routing/router.py": {
            "module_name": "routing",
            "roles": ["domain_logic"],
            "is_test": False, "is_generated": False, "is_config": False,
            "eligible_as_primary": True,
            "keywords": ["route"], "symbols": ["route"]},
    },
}
_MODULE_EDGES = {
    "edges": [
        {"from": "intake", "to": "routing", "edge_types": ["runtime_import"],
         "evidence": [{"source": "import_graph", "type": "runtime_import",
                       "from": "core/intake/validation.py",
                       "to": "core/routing/router.py", "confidence": "high"}],
         "evidence_count": 1, "confidence": "high",
         "direction": "outbound", "expand_by_default": True},
    ],
}
_TEST_MAP = {
    "production_to_tests": {
        "core/intake/validation.py": {
            "coverage": "direct",
            "tests": [{"test_file": "tests/test_intake_validation.py",
                       "relationship": "direct_import", "confidence": "high"}]},
    },
    "module_to_tests": {"intake": ["tests/test_intake.py"]},
}

_QUERY = "add a new validation rule for incoming tickets"


def _write_views(root: Path) -> None:
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "modules.json").write_text(json.dumps(_MODULES), encoding="utf-8")
    (idx / "file_roles.json").write_text(json.dumps(_FILE_ROLES), encoding="utf-8")
    (idx / "module_edges.json").write_text(json.dumps(_MODULE_EDGES), encoding="utf-8")
    (idx / "test_map.json").write_text(json.dumps(_TEST_MAP), encoding="utf-8")


def _run_intake(tmp_path: Path, monkeypatch, key: str, desc: str) -> int:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(intake.identity, "current", lambda: "t@example.com")
    return intake.run([key, desc])


def _trace(tmp_path: Path, key: str) -> dict:
    p = tmp_path / ".klc" / "tickets" / key / "retrieval_trace.json"
    assert p.exists(), "intake did not produce retrieval_trace.json"
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# AC-1 — intake → trace wiring (views present, deterministic ok trace)
# --------------------------------------------------------------------------- #
def test_intake_produces_trace_when_views_present(tmp_path, monkeypatch):
    _write_views(tmp_path)
    rc = _run_intake(tmp_path, monkeypatch, "KLC-900", _QUERY)
    assert rc == 0
    trace = _trace(tmp_path, "KLC-900")
    assert trace["status"] == "ok"
    assert trace["mode"] == "deterministic"          # no-model hot path
    assert trace["query"].strip() == _QUERY
    assert "intake" in trace["affected_modules_hint"]
    assert "core/intake/validation.py" in trace["files_to_read_first"]


def test_intake_trace_is_byte_reproducible(tmp_path, monkeypatch):
    _write_views(tmp_path)
    _run_intake(tmp_path, monkeypatch, "KLC-903", _QUERY)
    first = (tmp_path / ".klc" / "tickets" / "KLC-903"
             / "retrieval_trace.json").read_bytes()
    # a second intake --force over the same ticket must reproduce the trace byte-for-byte
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(intake.identity, "current", lambda: "t@example.com")
    assert intake.run(["KLC-903", _QUERY, "--force"]) == 0
    second = (tmp_path / ".klc" / "tickets" / "KLC-903"
              / "retrieval_trace.json").read_bytes()
    assert first == second


# --------------------------------------------------------------------------- #
# AC-2 — degrade-not-fail: no views → status:"unavailable", intake still exit 0
# --------------------------------------------------------------------------- #
def test_intake_degrades_without_views(tmp_path, monkeypatch):
    rc = _run_intake(tmp_path, monkeypatch, "KLC-901", _QUERY)
    assert rc == 0, "intake must never break when planning views are absent"
    trace = _trace(tmp_path, "KLC-901")
    assert trace["status"] == "unavailable"
    assert trace["confidence"] in {"high", "medium", "low"}
    assert trace["reasons"]


# --------------------------------------------------------------------------- #
# AC-3 — authority: intake/retriever NEVER writes meta.affected_modules
# --------------------------------------------------------------------------- #
def test_intake_never_writes_affected_modules(tmp_path, monkeypatch):
    _write_views(tmp_path)
    rc = _run_intake(tmp_path, monkeypatch, "KLC-902", _QUERY)
    assert rc == 0
    meta = json.loads((tmp_path / ".klc" / "tickets" / "KLC-902"
                       / "meta.json").read_text(encoding="utf-8"))
    # the retriever proposes a hint but must not touch the authoritative scope
    assert meta["affected_modules"] == []
    # ... even though the trace's advisory hint is non-empty
    assert _trace(tmp_path, "KLC-902")["affected_modules_hint"] == ["intake"]


def test_description_from_raw_strips_frontmatter():
    body = "---\nticket: KLC-1\ncreated: 2026-01-01\n---\nreal description here\n"
    assert intake._description_from_raw(body) == "real description here"
    assert intake._description_from_raw("no frontmatter") == "no frontmatter"


# --------------------------------------------------------------------------- #
# prompt-cascade accuracy — referenced fields exist in the retriever schema
# --------------------------------------------------------------------------- #
def _schema_keys() -> set[str]:
    """Every field name (top-level + nested) a real trace actually emits."""
    spec = importlib.util.spec_from_file_location("planning_retriever", _RETRIEVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    trace = mod.build_trace(_QUERY, "deterministic", _MODULES, _FILE_ROLES,
                            _MODULE_EDGES, _TEST_MAP)
    keys = set(trace)
    for pm in trace["primary_modules"]:
        keys |= set(pm)
    for n in trace["conditional_neighbors"]:
        keys |= set(n)
    return keys


# the trace fields the prompt cascade names in backticks
_REFERENCED_FIELDS = {
    "status", "mode", "query", "confidence", "reasons",
    "primary_modules", "files_to_read_first", "files_likely_to_edit",
    "tests_to_read_or_run", "conditional_neighbors", "affected_modules_hint",
    "unknown_or_ambiguous_modules", "stop_rules",
    "module_name", "condition",
}

_CONSUMING_PROMPTS = ("discovery.md", "discovery-lite.md", "design.md",
                      "design-scout.md", "review.md", "test-planner.md")


def test_referenced_fields_all_exist_in_schema():
    missing = _REFERENCED_FIELDS - _schema_keys()
    assert not missing, f"prompts reference fields the retriever never emits: {missing}"


def test_every_consuming_prompt_reads_the_trace():
    for name in _CONSUMING_PROMPTS:
        text = (_AGENTS / name).read_text(encoding="utf-8")
        assert "retrieval_trace.json" in text, f"{name} does not consume the trace"


def test_slice_fields_are_consumed_across_prompts():
    combined = "".join((_AGENTS / n).read_text(encoding="utf-8")
                       for n in _CONSUMING_PROMPTS)
    for field in ("files_to_read_first", "files_likely_to_edit",
                  "tests_to_read_or_run", "conditional_neighbors", "stop_rules"):
        assert field in combined, f"no prompt loads the trace's `{field}` slice"


def test_design_paths_consume_conditional_neighbors():
    """P2-2/P2-3: the design + discovery-lite + design-scout paths must consume
    conditional_neighbors (they can come from retriever logic, not only
    module_edges), else part of the AC-4 minimal slice is missed."""
    for name in ("design.md", "discovery-lite.md", "design-scout.md"):
        text = (_AGENTS / name).read_text(encoding="utf-8")
        assert "conditional_neighbors" in text, \
            f"{name} does not consume conditional_neighbors"


def _edit_distance_le_1(a: str, b: str) -> bool:
    """True iff *a* and *b* differ by at most one insert/delete/substitution
    (and are not equal)."""
    if a == b:
        return False
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = j = diff = 0
    while i < len(short) and j < len(long):
        if short[i] != long[j]:
            diff += 1
            j += 1
            if diff > 1:
                return False
        else:
            i += 1
            j += 1
    return True


# Legit snake_case backtick tokens that are morphologically near a trace field
# but are real fields of OTHER artifacts (not mistyped trace-field references).
# Keep this list tiny and explicit — every entry is a deliberate exception.
_NON_TRACE_FIELD_ALLOWLIST: set[str] = set()


def test_no_field_style_backtick_token_is_a_near_miss_of_a_schema_field():
    """AC-5 (strengthened): scan EVERY backticked snake_case token in the
    consuming prompts. A token that is not a real schema key but IS a
    singular/plural or edit-distance-1 variant of a real multi-word trace field
    (e.g. `conditional_neighbor` for `conditional_neighbors`) is a mistyped
    field reference and must fail — this is exactly the class the earlier
    curated-blocklist check could miss."""
    schema = _schema_keys()
    targets = {k for k in schema if "_" in k}          # multi-word trace fields
    token_re = re.compile(r"`([a-z][a-z0-9_]*)`")
    offenders: list[str] = []
    for name in _CONSUMING_PROMPTS:
        text = (_AGENTS / name).read_text(encoding="utf-8")
        for tok in sorted(set(token_re.findall(text))):
            if "_" not in tok or tok in schema or tok in _NON_TRACE_FIELD_ALLOWLIST:
                continue
            near = [k for k in targets
                    if tok == k.rstrip("s") or tok + "s" == k
                    or _edit_distance_le_1(tok, k)]
            if near:
                offenders.append(f"{name}: `{tok}` looks like trace field "
                                 f"`{near[0]}` but is not a real schema key")
    assert not offenders, "; ".join(offenders)


def test_prompts_do_not_reference_nonexistent_trace_fields():
    """Guard against the tempting-but-wrong field names for the trace."""
    schema = _schema_keys()
    wrong = {"files_to_edit", "tests_to_run", "stop_conditions", "primary_files",
             "files_to_read", "read_first", "files_likely_edited",
             "conditional_modules", "affected_modules_hints"}
    # sanity: none of these are real
    assert not (wrong & schema), "blocklist accidentally contains a real field"
    for name in _CONSUMING_PROMPTS:
        text = (_AGENTS / name).read_text(encoding="utf-8")
        for bad in wrong:
            # word-boundary match so a real field (files_to_read_first) is not
            # flagged by a wrong prefix (files_to_read).
            assert not re.search(rf"\b{re.escape(bad)}\b", text), \
                f"{name} references nonexistent trace field `{bad}`"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
