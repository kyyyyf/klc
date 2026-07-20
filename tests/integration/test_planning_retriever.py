"""KLC-068 — query-time planning-retriever: real-substrate fixture tests.

Offline & deterministic: builds real planning-view JSON (the FROZEN schemas of
modules.json v2 / file_roles.json / module_edges.json / test_map.json) in
tmp_path, runs planning-retriever.py to produce a retrieval_trace.json, and
asserts the trace schema, deterministic ranking, degrade paths, the authority
boundary, and the KLC-067 eval seam end-to-end. No network, no LLM.

Fixture module map:
  intake   -> core/intake/    (keywords: ticket/intake/validation/parse)
  routing  -> core/routing/   (keywords: route/dispatch)
  review   -> core/agents/review (file-stem module)
  files override: core/common/paths.py is shared (member_of intake+routing)
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "core" / "skills" / "planning-retriever.py"
_EVAL = _FW_ROOT / "core" / "skills" / "planning-eval.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("planning_retriever", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# fixture views (real frozen schemas)
# --------------------------------------------------------------------------- #
MODULES = {
    "modules": [
        {"name": "intake", "path": "core/intake/",
         "primary_entrypoints": ["core/intake/parser.py"],
         "public_surfaces": ["core/intake/validation.py"],
         "test_files": ["tests/test_intake.py"],
         "summary": "Parses and validates incoming ticket descriptions.",
         "keywords": ["ticket", "intake", "validation", "parse"]},
        {"name": "routing", "path": "core/routing/",
         "summary": "Routes requests to the right handler.",
         "keywords": ["route", "dispatch"]},
        {"name": "review", "path": "core/agents/review",
         "summary": "Review agent.", "keywords": ["review"]},
        # UI module whose own signal does NOT contain the token 'ui' — so a role-only
        # 'ui' query must match through its file's role, not the module keywords.
        {"name": "ui", "path": "core/ui/",
         "summary": "User interface layer.", "keywords": ["interface", "widget"]},
    ],
    "files": {
        "core/common/paths.py": {"primary_module": None,
                                 "member_of": ["intake", "routing"]},
    },
}

FILE_ROLES = {
    "files": {
        "core/intake/validation.py": {
            "module_name": "intake",
            "roles": ["public_surface", "domain_logic"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["validate", "ticket", "schema"],
            "symbols": ["validate_ticket", "ValidationResult"],
            "confidence": "high"},
        "core/intake/parser.py": {
            "module_name": "intake",
            "roles": ["entrypoint", "domain_logic"],
            "is_entrypoint": True, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["parse", "ticket"],
            "symbols": ["parse_ticket"], "confidence": "high"},
        "core/intake/schema.py": {
            "module_name": "intake",
            "roles": ["types"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["schema", "ticket"],
            "symbols": ["TicketSchema"], "confidence": "high"},
        "core/routing/router.py": {
            "module_name": "routing",
            "roles": ["domain_logic"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["route", "dispatch"],
            "symbols": ["route"], "confidence": "high"},
        "core/common/paths.py": {
            "module_name": None,
            "roles": ["shared"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": False,
            "keywords": ["path", "resolve"],
            "symbols": ["resolve_path"], "confidence": "high"},
        "core/intake/ticket_pb2.py": {
            "module_name": "intake",
            "roles": ["generated"],
            "is_entrypoint": False, "is_test": False, "is_generated": True,
            "is_config": False, "eligible_as_primary": False,
            "keywords": ["ticket", "validation"],
            "symbols": [], "confidence": "medium"},
        # persistence file whose ONLY query-matchable signal is its ROLE (its
        # keywords/symbols do not contain 'persistence') — exercises role scoring.
        "core/intake/store.py": {
            "module_name": "intake",
            "roles": ["persistence"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["storage", "backend"],
            "symbols": ["save_record"], "confidence": "medium"},
        # MALFORMED record: a test file flagged eligible_as_primary:true. The
        # defensive re-check must still keep it out of files_to_read_first.
        "core/intake/test_helpers.py": {
            "module_name": "intake",
            "roles": ["test", "domain_logic"],
            "is_entrypoint": False, "is_test": True, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["validation", "helper"],
            "symbols": ["make_ticket"], "confidence": "low"},
        # UI file whose ONLY query-matchable signal is the short role token 'ui'
        # (keywords/symbols do not contain it) — exercises short-role-token matching.
        "core/ui/dashboard.py": {
            "module_name": "ui",
            "roles": ["ui"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["widget", "screen"],
            "symbols": ["render"], "confidence": "high"},
    }
}

MODULE_EDGES = {
    "edges": [
        {"from": "intake", "to": "routing",
         "edge_types": ["runtime_import"],
         "evidence": [{"source": "import_graph", "type": "runtime_import",
                       "from": "core/intake/validation.py",
                       "to": "core/routing/router.py", "confidence": "high"}],
         "evidence_count": 2, "confidence": "high",
         "direction": "outbound", "expand_by_default": True},
    ]
}

TEST_MAP = {
    "production_to_tests": {
        "core/intake/validation.py": {
            "coverage": "direct",
            "tests": [{"test_file": "tests/test_intake_validation.py",
                       "relationship": "direct_import", "confidence": "high"}]},
        "core/intake/parser.py": {"coverage": "none", "tests": []},
    },
    "module_to_tests": {
        "intake": ["tests/test_intake.py", "tests/test_intake_validation.py"],
    },
}

INVENTORY = {"symbols": [
    {"name": "validate_ticket", "kind": "function",
     "file": "core/intake/validation.py", "visibility": "public"},
]}

QUERY = "add a new validation rule for incoming tickets"


def _write_views(idx: Path, *, omit: set[str] | None = None) -> dict:
    """Write the fixture views into *idx*; return the --in-* arg map."""
    omit = omit or set()
    idx.mkdir(parents=True, exist_ok=True)
    payloads = {
        "modules": ("modules.json", MODULES),
        "file_roles": ("file_roles.json", FILE_ROLES),
        "module_edges": ("module_edges.json", MODULE_EDGES),
        "test_map": ("test_map.json", TEST_MAP),
        "inventory": ("inventory.json", INVENTORY),
    }
    args: dict[str, Path] = {}
    for key, (fname, data) in payloads.items():
        p = idx / fname
        if key not in omit:
            p.write_text(json.dumps(data), encoding="utf-8")
        args[key] = p
    return args


def _run(ticket_dir: Path, out: Path, in_args: dict, *, query: str = QUERY,
         mode: str | None = None, env_extra: dict | None = None,
         ) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(ticket_dir.parents[2] if len(ticket_dir.parents) >= 3
                              else ticket_dir)
    if env_extra:
        env.update(env_extra)
    argv = [sys.executable, str(_SKILL),
            "--ticket", ticket_dir.name, "--query", query,
            "--in-modules", str(in_args["modules"]),
            "--in-file-roles", str(in_args["file_roles"]),
            "--in-module-edges", str(in_args["module_edges"]),
            "--in-test-map", str(in_args["test_map"]),
            "--in-inventory", str(in_args["inventory"]),
            "--out", str(out)]
    if mode:
        argv += ["--mode", mode]
    return subprocess.run(argv, capture_output=True, text=True, env=env)


def _setup(tmp_path: Path):
    idx = tmp_path / ".klc" / "index"
    in_args = _write_views(idx)
    ticket_dir = tmp_path / ".klc" / "tickets" / "KLC-999"
    ticket_dir.mkdir(parents=True, exist_ok=True)
    out = ticket_dir / "retrieval_trace.json"
    return idx, in_args, ticket_dir, out


# --------------------------------------------------------------------------- #
# AC-1 / AC-2 — CLI + full trace schema
# --------------------------------------------------------------------------- #
_SCHEMA_KEYS = {
    "status", "mode", "query", "primary_modules", "files_to_read_first",
    "files_likely_to_edit", "tests_to_read_or_run", "conditional_neighbors",
    "affected_modules_hint", "unknown_or_ambiguous_modules", "stop_rules",
    "confidence", "reasons",
}


def test_cli_writes_trace_to_out(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    proc = _run(ticket_dir, out, in_args)
    assert proc.returncode == 0, proc.stderr
    assert out.exists()


def test_trace_has_full_schema(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)
    trace = json.loads(out.read_text())
    assert _SCHEMA_KEYS <= set(trace), _SCHEMA_KEYS - set(trace)
    assert isinstance(trace["primary_modules"], list)
    assert isinstance(trace["files_to_read_first"], list)
    assert isinstance(trace["files_likely_to_edit"], list)
    assert isinstance(trace["tests_to_read_or_run"], list)
    assert isinstance(trace["conditional_neighbors"], list)
    assert isinstance(trace["affected_modules_hint"], list)
    assert isinstance(trace["unknown_or_ambiguous_modules"], list)
    assert isinstance(trace["stop_rules"], list)
    assert isinstance(trace["reasons"], list)
    assert trace["confidence"] in {"high", "medium", "low"}
    assert trace["query"] == QUERY


# --------------------------------------------------------------------------- #
# AC-3 — mode default + assisted opt-in
# --------------------------------------------------------------------------- #
def test_default_mode_is_deterministic(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)
    assert json.loads(out.read_text())["mode"] == "deterministic"


def test_assisted_mode_is_opt_in_no_model_on_intake(tmp_path):
    """assisted is opt-in; offline it degrades to the deterministic layers and
    never invokes a model. The deterministic path must import no model client."""
    _, in_args, ticket_dir, out = _setup(tmp_path)
    proc = _run(ticket_dir, out, in_args, mode="assisted")
    assert proc.returncode == 0, proc.stderr
    trace = json.loads(out.read_text())
    # assisted requested, but offline it falls back and says so in reasons
    assert any("assisted" in r.lower() for r in trace["reasons"])
    # source must not import an LLM/model or network client (determinism guarantee)
    src = _SKILL.read_text()
    for banned in ("anthropic", "openai", "requests", "urllib.request",
                   "http.client", "socket"):
        assert banned not in src, f"deterministic skill must not use {banned}"


# --------------------------------------------------------------------------- #
# AC-4 — deterministic ranking
# --------------------------------------------------------------------------- #
def test_query_ranks_matching_module_first(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)
    trace = json.loads(out.read_text())
    assert trace["primary_modules"], "expected at least one primary module"
    assert trace["primary_modules"][0]["module_name"] == "intake"
    assert trace["confidence"] == "high"


def test_eligible_files_ranked_before_ineligible(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)
    ftr = json.loads(out.read_text())["files_to_read_first"]
    # validation.py (public_surface, strong keyword+symbol hits) leads
    assert ftr[0] == "core/intake/validation.py"
    # shared + generated files never appear as primary reads
    assert "core/common/paths.py" not in ftr
    assert "core/intake/ticket_pb2.py" not in ftr


def test_likely_to_edit_are_eligible_only(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)
    edit = json.loads(out.read_text())["files_likely_to_edit"]
    assert "core/intake/validation.py" in edit
    assert "core/common/paths.py" not in edit
    assert "core/intake/ticket_pb2.py" not in edit


def test_neighbor_expanded_one_hop_via_module_edges(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)
    neigh = json.loads(out.read_text())["conditional_neighbors"]
    names = {n["module_name"] for n in neigh}
    assert "routing" in names
    for n in neigh:
        assert n.get("condition")


def test_tests_mapped_via_test_map(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)
    tests = json.loads(out.read_text())["tests_to_read_or_run"]
    assert "tests/test_intake_validation.py" in tests


def test_every_primary_module_has_reasons(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)
    for pm in json.loads(out.read_text())["primary_modules"]:
        assert pm["confidence"] in {"high", "medium", "low"}
        assert pm["reasons"], "each primary module needs reasons"


def test_affected_modules_hint_is_primary_modules(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)
    trace = json.loads(out.read_text())
    assert "intake" in trace["affected_modules_hint"]


# --------------------------------------------------------------------------- #
# AC-5 — degrade-not-fail + confidence enum + reasons always present
# --------------------------------------------------------------------------- #
def test_missing_views_status_unavailable_exit0(tmp_path):
    idx = tmp_path / ".klc" / "index"
    in_args = _write_views(idx, omit={"modules", "file_roles", "module_edges",
                                       "test_map", "inventory"})
    ticket_dir = tmp_path / ".klc" / "tickets" / "KLC-999"
    ticket_dir.mkdir(parents=True, exist_ok=True)
    out = ticket_dir / "retrieval_trace.json"
    proc = _run(ticket_dir, out, in_args)
    assert proc.returncode == 0, proc.stderr
    trace = json.loads(out.read_text())
    assert trace["status"] == "unavailable"
    assert trace["confidence"] in {"high", "medium", "low"}
    assert trace["reasons"]


def test_weak_match_low_confidence_widened_search(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    proc = _run(ticket_dir, out, in_args,
                query="quantum blockchain hyperloop telemetry")
    assert proc.returncode == 0
    trace = json.loads(out.read_text())
    assert trace["confidence"] == "low"
    assert trace["reasons"]
    assert any("widen" in r.lower() for r in trace["reasons"])


def test_confidence_enum_and_reasons_always_present(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    for q in (QUERY, "nonsense zzz", ""):
        _run(ticket_dir, out, in_args, query=q)
        trace = json.loads(out.read_text())
        assert trace["confidence"] in {"high", "medium", "low"}
        assert isinstance(trace["reasons"], list) and trace["reasons"]


def test_medium_confidence_on_path_only_match(tmp_path):
    """A query that hits only a module name / path token (no keyword/symbol match)
    scores lower and yields the medium confidence tier."""
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args, query="routing")
    trace = json.loads(out.read_text())
    assert trace["primary_modules"][0]["module_name"] == "routing"
    assert trace["confidence"] == "medium"


def test_modules_absent_degrades_to_unavailable(tmp_path):
    """FIX-1: modules.json is a required planning view — without it every file
    resolves to orphan and there is no module attribution, so a status:"ok" trace
    with empty primary_modules/hint would mislead. When modules.json is absent (but
    file_roles.json is present) the trace must degrade to status:"unavailable"
    (exit 0), symmetric with the file_roles-absent case."""
    idx = tmp_path / ".klc" / "index"
    in_args = _write_views(idx, omit={"modules"})
    ticket_dir = tmp_path / ".klc" / "tickets" / "KLC-999"
    ticket_dir.mkdir(parents=True, exist_ok=True)
    out = ticket_dir / "retrieval_trace.json"
    proc = _run(ticket_dir, out, in_args)
    assert proc.returncode == 0, proc.stderr
    trace = json.loads(out.read_text())
    assert trace["status"] == "unavailable"
    assert trace["primary_modules"] == []
    assert trace["affected_modules_hint"] == []
    assert any("modules.json" in r for r in trace["reasons"])


def test_shared_file_match_surfaces_member_modules(tmp_path):
    """FIX-2: a query strongly matching a SHARED file (primary_module=None,
    member_of set) must surface its member modules — the KLC-066 resolver models
    shared files via member_of precisely so they are not stranded. The shared file
    itself stays out of files_to_read_first (not eligible), but its member modules
    appear in the hint and/or conditional neighbours."""
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args, query="resolve path")
    trace = json.loads(out.read_text())
    surfaced = set(trace["affected_modules_hint"]) | {
        n["module_name"] for n in trace["conditional_neighbors"]}
    assert {"intake", "routing"} <= surfaced, surfaced
    # the shared file is never an eligible primary read
    assert "core/common/paths.py" not in trace["files_to_read_first"]
    # FIX-B: the surfaced member modules' module-level tests are included too
    # (test_intake.py comes ONLY from module_to_tests[intake], not any read file)
    assert "tests/test_intake.py" in trace["tests_to_read_or_run"]


def test_role_only_short_token_query_selects_ui(tmp_path):
    """FIX-A: short role tokens like 'ui' must participate in role matching. A
    role-only 'ui' query selects the UI file/module (score > 0, primary set), not
    the widened all-eligible fallback."""
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args, query="ui")
    trace = json.loads(out.read_text())
    assert trace["primary_modules"], "short role token should yield a primary module"
    assert "ui" in {m["module_name"] for m in trace["primary_modules"]}
    assert trace["files_to_read_first"][0] == "core/ui/dashboard.py"
    # not the widened fallback: unrelated modules must not lead
    assert "core/routing/router.py" not in trace["files_to_read_first"]


def test_role_only_query_selects_by_role(tmp_path):
    """FIX-3: file_roles roles participate in matching. A role-only query
    ('persistence') selects the file whose role matches (score > 0), not the
    widened all-eligible fallback."""
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args, query="persistence")
    trace = json.loads(out.read_text())
    assert trace["files_to_read_first"], "role match should select a file"
    assert trace["files_to_read_first"][0] == "core/intake/store.py"
    # not the widened fallback: an unrelated module's file must not lead
    assert "core/routing/router.py" not in trace["files_to_read_first"]
    assert trace["primary_modules"], "role match should yield a primary module"


def test_malformed_eligible_test_file_excluded(tmp_path):
    """FIX-4: defensive eligibility — a test/generated/config file flagged
    eligible_as_primary:true (malformed file_roles.json) must still be kept out of
    files_to_read_first."""
    _, in_args, ticket_dir, out = _setup(tmp_path)
    _run(ticket_dir, out, in_args)  # QUERY matches test_helpers.py via 'validation'
    trace = json.loads(out.read_text())
    assert "core/intake/test_helpers.py" not in trace["files_to_read_first"]
    assert "core/intake/test_helpers.py" not in trace["files_likely_to_edit"]


def test_file_roles_absent_degrades_to_unavailable(tmp_path):
    """file_roles.json is the sole source of the read slice + the eval seam's
    candidate list; its absence must degrade to status:unavailable (exit 0), even
    when modules.json is present, rather than a misleading status:ok/empty trace."""
    idx = tmp_path / ".klc" / "index"
    in_args = _write_views(idx, omit={"file_roles"})
    ticket_dir = tmp_path / ".klc" / "tickets" / "KLC-999"
    ticket_dir.mkdir(parents=True, exist_ok=True)
    out = ticket_dir / "retrieval_trace.json"
    proc = _run(ticket_dir, out, in_args)
    assert proc.returncode == 0, proc.stderr
    trace = json.loads(out.read_text())
    assert trace["status"] == "unavailable"
    assert trace["files_to_read_first"] == []
    assert any("file_roles" in r for r in trace["reasons"])


# --------------------------------------------------------------------------- #
# AC-6 — authority boundary + resolver reuse
# --------------------------------------------------------------------------- #
def test_never_writes_meta_affected_modules(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    meta = ticket_dir / "meta.json"
    meta.write_text(json.dumps({"ticket": "KLC-999", "affected_modules": []}))
    before = meta.read_text()
    _run(ticket_dir, out, in_args)
    assert meta.read_text() == before, "retriever must never touch meta.json"


def test_uses_module_membership_resolver():
    mod = _load_skill()
    # the skill must resolve membership through the KLC-066 resolver
    res = mod._mm.file_to_module("core/common/paths.py", MODULES)
    assert res["member_of"] == ["intake", "routing"]


def test_no_private_matcher_in_source():
    src = _SKILL.read_text()
    assert "module_membership" in src
    assert "file_to_module" in src
    # no reintroduced private longest-prefix matcher
    assert "longest_prefix" not in src.lower()
    assert "startswith(mpath" not in src


# --------------------------------------------------------------------------- #
# AC-7 — KLC-067 eval seam filled end-to-end
# --------------------------------------------------------------------------- #
def test_eval_computes_recall_from_produced_trace(tmp_path):
    """Produce a real trace with the retriever, then run planning-eval over a
    fixture ticket carrying that trace and assert recall@N is computed (ok),
    not 'unavailable'. This proves the KLC-067 seam is filled."""
    idx = tmp_path / ".klc" / "index"
    in_args = _write_views(idx)
    modules_path = idx / "modules.json"

    tickets_root = tmp_path / ".klc" / "tickets"
    tdir = tickets_root / "TCK-1"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "meta.json").write_text(json.dumps(
        {"ticket": "TCK-1", "affected_modules": ["intake"]}))
    # ground-truth changed file (stored-patch seam — no git needed)
    (tdir / "changed_files.txt").write_text("core/intake/validation.py\n")

    trace_out = tdir / "retrieval_trace.json"
    proc = _run(tdir, trace_out, in_args)
    assert proc.returncode == 0, proc.stderr
    produced = json.loads(trace_out.read_text())
    assert "core/intake/validation.py" in produced["files_to_read_first"]

    # now run the KLC-067 eval over this corpus
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(tmp_path)
    report = tmp_path / "eval_report.json"
    ev = subprocess.run(
        [sys.executable, str(_EVAL),
         "--tickets", str(tickets_root),
         "--modules", str(modules_path),
         "--repo", str(tmp_path),
         "--out", str(report)],
        capture_output=True, text=True, env=env)
    assert ev.returncode == 0, ev.stderr
    rm = json.loads(report.read_text())["retrieval_metrics"]
    assert rm["status"] == "ok", rm
    assert rm["recall_at_5"] == pytest.approx(1.0)
    assert rm["recall_at_10"] == pytest.approx(1.0)
    assert rm["precision_at_10"] is not None


# --------------------------------------------------------------------------- #
# AC-8 — byte-reproducibility
# --------------------------------------------------------------------------- #
def test_deterministic_output_is_byte_reproducible(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    out2 = ticket_dir / "trace2.json"
    _run(ticket_dir, out, in_args)
    _run(ticket_dir, out2, in_args)
    assert out.read_bytes() == out2.read_bytes()


# --------------------------------------------------------------------------- #
# CLI arg errors
# --------------------------------------------------------------------------- #
def test_missing_required_query_exits_2(tmp_path):
    _, in_args, ticket_dir, out = _setup(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(_SKILL), "--ticket", "KLC-999",
         "--in-modules", str(in_args["modules"]), "--out", str(out)],
        capture_output=True, text=True)
    assert proc.returncode == 2
