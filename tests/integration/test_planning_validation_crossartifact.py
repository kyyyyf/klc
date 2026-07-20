"""KLC-071 step-7 — planning_validate.py cross-artifact checks (file_roles /
module_edges / retrieval consistency). Each new check has a negative test."""
import sys
from pathlib import Path

_skills = Path(__file__).parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(_skills))
import planning_validate as pv  # noqa: E402


_MODULES = {
    "modules": [
        {"name": "intake", "path": "core/intake"},
        {"name": "routing", "path": "core/routing"},
    ],
    "files": {
        "core/common/paths.py": {"primary_module": None,
                                 "member_of": ["intake", "routing"]},
    },
}

# A consistent file_roles: the shared file is NOT eligible, generated not eligible,
# the test file not eligible, the domain file eligible.
_GOOD_ROLES = {"files": {
    "core/intake/validation.py": {"module_name": "intake", "roles": ["domain_logic"],
                                  "is_test": False, "is_generated": False,
                                  "is_config": False, "eligible_as_primary": True},
    "core/common/paths.py": {"module_name": None, "roles": ["shared"],
                             "is_test": False, "is_generated": False,
                             "is_config": False, "eligible_as_primary": False},
    "vendor/gen.py": {"module_name": None, "roles": ["generated"],
                      "is_test": False, "is_generated": True,
                      "is_config": False, "eligible_as_primary": False},
    "tests/test_x.py": {"module_name": "intake", "roles": ["test"],
                        "is_test": True, "is_generated": False,
                        "is_config": False, "eligible_as_primary": False},
}}


def test_consistent_cross_artifact_no_new_warnings():
    r = pv.validate(_MODULES, files_list=None, file_roles=_GOOD_ROLES)
    joined = " ".join(r["warnings"])
    assert "eligible_as_primary" not in joined
    assert "generated" not in joined


def test_shared_file_eligible_true_flagged():
    """membership⇔eligibility: a shared file (primary_module null) must be
    eligible_as_primary:false; the reverse is a warning."""
    bad = {"files": dict(_GOOD_ROLES["files"])}
    bad["files"]["core/common/paths.py"] = {
        **_GOOD_ROLES["files"]["core/common/paths.py"], "eligible_as_primary": True}
    r = pv.validate(_MODULES, files_list=None, file_roles=bad)
    assert any("shared" in w and "eligible" in w for w in r["warnings"])


def test_generated_eligible_true_flagged():
    """generated/vendor files must never be eligible as primary."""
    bad = {"files": dict(_GOOD_ROLES["files"])}
    bad["files"]["vendor/gen.py"] = {
        **_GOOD_ROLES["files"]["vendor/gen.py"], "eligible_as_primary": True}
    r = pv.validate(_MODULES, files_list=None, file_roles=bad)
    assert any("generated" in w and "eligible" in w for w in r["warnings"])


def test_test_file_eligible_true_flagged():
    """A test file must not be eligible as a primary (production) file."""
    bad = {"files": dict(_GOOD_ROLES["files"])}
    bad["files"]["tests/test_x.py"] = {
        **_GOOD_ROLES["files"]["tests/test_x.py"], "eligible_as_primary": True}
    r = pv.validate(_MODULES, files_list=None, file_roles=bad)
    assert any("test" in w and "eligible" in w for w in r["warnings"])


def test_reverse_drift_stale_file_roles_marks_shared_flagged():
    """FIX-2a: modules.json resolves the file to a real primary module, but a stale
    file_roles.json marks it shared/ineligible → the divergence must be flagged
    (the reverse direction of the membership⇔eligibility check)."""
    # core/intake/validation.py resolves to 'intake' via longest-prefix (owned), but
    # file_roles wrongly marks it shared + ineligible.
    stale = {"files": {
        "core/intake/validation.py": {"module_name": None, "roles": ["shared"],
                                      "is_test": False, "is_generated": False,
                                      "is_config": False, "eligible_as_primary": False},
    }}
    r = pv.validate(_MODULES, files_list=None, file_roles=stale)
    assert any("validation.py" in w and "intake" in w and "shared" in w
               for w in r["warnings"])


def test_high_evidence_edge_without_file_evidence_flagged():
    """A high evidence_count edge must carry file-level evidence."""
    edges = {"edges": [
        {"from": "intake", "to": "routing", "evidence_count": 3,
         "confidence": "high", "evidence": []},  # no file-level evidence
    ]}
    r = pv.validate(_MODULES, files_list=None, module_edges=edges)
    assert any("evidence" in w and ("intake" in w or "routing" in w)
               for w in r["warnings"])


def test_high_evidence_edge_with_evidence_ok():
    edges = {"edges": [
        {"from": "intake", "to": "routing", "evidence_count": 3, "confidence": "high",
         "evidence": [{"source": "import_graph", "type": "runtime_import",
                       "from": "core/intake/a.py", "to": "core/routing/b.py"}]},
    ]}
    r = pv.validate(_MODULES, files_list=None, module_edges=edges)
    assert not any("file-level evidence" in w for w in r["warnings"])


def test_retrieval_unknown_module_flagged():
    """retrieval refs must point at real modules."""
    trace = {"primary_modules": [{"module_name": "ghost"}],
             "files_to_read_first": []}
    r = pv.validate(_MODULES, files_list=None, retrieval=trace)
    assert any("ghost" in w for w in r["warnings"])


def test_retrieval_unknown_file_flagged():
    """retrieval file refs must exist in file_roles/inventory."""
    trace = {"primary_modules": [{"module_name": "intake"}],
             "files_to_read_first": ["core/does/not/exist.py"]}
    r = pv.validate(_MODULES, files_list=None, file_roles=_GOOD_ROLES,
                    retrieval=trace)
    assert any("exist.py" in w for w in r["warnings"])


def test_retrieval_ref_to_inventory_file_absent_from_file_roles_not_flagged():
    """FIX-2b: a retrieval ref to a real file present in inventory but ABSENT from
    file_roles must not be falsely flagged 'unknown file' — the file universe is
    file_roles ∪ inventory files (the phantom _inventory_symbols term is gone)."""
    inventory = {"symbols": [
        {"name": "helper", "kind": "function", "file": "core/intake/only_inv.py",
         "line": 1, "signature": "def helper(", "visibility": "public",
         "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
    ]}
    trace = {"primary_modules": [{"module_name": "intake"}],
             "files_to_read_first": ["core/intake/only_inv.py"]}  # in inv, not roles
    r = pv.validate(_MODULES, files_list=None, file_roles=_GOOD_ROLES,
                    retrieval=trace, inventory=inventory)
    assert not any("only_inv.py" in w for w in r["warnings"])
    # sanity: a genuinely unknown file IS still flagged.
    trace2 = {"primary_modules": [{"module_name": "intake"}],
              "files_to_read_first": ["core/nope/ghost.py"]}
    r2 = pv.validate(_MODULES, files_list=None, file_roles=_GOOD_ROLES,
                     retrieval=trace2, inventory=inventory)
    assert any("ghost.py" in w for w in r2["warnings"])


def test_retrieval_refs_degrade_when_file_roles_absent():
    """FIX (P2): inventory WIDENS file_roles, it must not REPLACE it. With file_roles
    ABSENT, the retrieval file-refs check degrades (skipped + noted) rather than
    validating against inventory alone — a real symbol-less config/doc target must not
    be false-flagged, and --strict must not fail on it."""
    inventory = {"symbols": [
        {"name": "helper", "kind": "function", "file": "core/intake/has_syms.py",
         "line": 1, "signature": "def helper(", "visibility": "public",
         "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"}]}
    # a real config file with NO inventory symbols.
    trace = {"primary_modules": [{"module_name": "intake"}],
             "files_to_read_first": ["config/app.yml"]}
    r = pv.validate(_MODULES, files_list=None, file_roles=None,
                    retrieval=trace, inventory=inventory)
    assert not any("app.yml" in w for w in r["warnings"])
    assert not any("unknown file" in w for w in r["warnings"])
    assert any("file_roles" in e and "retrieval" in e for e in r["errors"])
    # the MODULE check still runs even without file_roles.
    bad = {"primary_modules": [{"module_name": "ghost"}], "files_to_read_first": []}
    r2 = pv.validate(_MODULES, files_list=None, file_roles=None, retrieval=bad,
                     inventory=inventory)
    assert any("ghost" in w for w in r2["warnings"])


def test_cli_strict_not_failed_by_degraded_retrieval(tmp_path):
    """FIX (P2) at the CLI: --strict must not fail merely because file_roles.json is
    absent and a retrieval ref points at a symbol-less file."""
    import json as _json
    mp = tmp_path / "modules.json"
    mp.write_text(_json.dumps(_MODULES), encoding="utf-8")
    inv = tmp_path / "inventory.json"
    inv.write_text(_json.dumps({"symbols": [
        {"name": "h", "kind": "function", "file": "core/intake/x.py", "line": 1,
         "signature": "def h(", "visibility": "public", "source_of_truth": "ast_grep",
         "lang": "python", "rule": "py-public-api"}]}), encoding="utf-8")
    tr = tmp_path / "trace.json"
    tr.write_text(_json.dumps({"primary_modules": [{"module_name": "intake"}],
                               "files_to_read_first": ["config/app.yml"]}),
                  encoding="utf-8")
    rc = pv.main(["--in-modules", str(mp), "--in-inventory", str(inv),
                  "--in-retrieval", str(tr),
                  "--in-file-roles", str(tmp_path / "nope.json"),
                  "--in-module-edges", str(tmp_path / "nope2.json"), "--strict"])
    assert rc == 0


def test_cross_checks_degrade_without_inputs():
    """No file_roles / module_edges / retrieval → recorded as not-checked, not fatal."""
    r = pv.validate(_MODULES, files_list=None)
    assert r["errors"] or True  # must not raise; cross-checks simply skipped
    assert "eligibility_checked" in r["counts"]
    assert r["counts"]["eligibility_checked"] is False
