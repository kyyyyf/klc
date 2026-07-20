"""KLC-071 step-5 — file_roles.json deterministic role classification."""
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import file_roles as fr  # noqa: E402

_MODULES = {
    "modules": [
        {"name": "intake", "path": "core/intake",
         "primary_entrypoints": ["core/intake/cli.py"]},
        {"name": "routing", "path": "core/routing"},
    ],
    "files": {
        "core/common/paths.py": {"primary_module": None,
                                 "member_of": ["intake", "routing"]},
    },
}

_STRUCTURAL = {"entry_points": ["core/intake/cli.py"], "source_roots": []}

_INVENTORY = {"symbols": [
    {"name": "validate_ticket", "kind": "function", "file": "core/intake/validation.py",
     "line": 1, "signature": "def validate_ticket(", "visibility": "public",
     "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
    {"name": "ValidationResult", "kind": "class", "file": "core/intake/validation.py",
     "line": 5, "signature": "class ValidationResult", "visibility": "public",
     "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
    {"name": "helper", "kind": "function", "file": "core/common/paths.py",
     "line": 1, "signature": "def helper(", "visibility": "public",
     "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
    {"name": "main", "kind": "function", "file": "core/intake/cli.py",
     "line": 1, "signature": "def main(", "visibility": "public",
     "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
    {"name": "Color", "kind": "enum", "file": "core/intake/types.py",
     "line": 1, "signature": "class Color(Enum)", "visibility": "public",
     "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
    {"name": "test_it", "kind": "function", "file": "tests/test_validation.py",
     "line": 1, "signature": "def test_it(", "visibility": "public",
     "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
]}


def _build(inventory=None, modules=None, structural=None):
    return fr.build_file_roles(
        inventory if inventory is not None else _INVENTORY,
        modules if modules is not None else _MODULES,
        structural if structural is not None else _STRUCTURAL,
    )


def test_domain_logic_file_is_eligible_primary():
    """AC-1: a file with public symbols and no disqualifier is domain_logic + eligible."""
    files = _build()["files"]
    v = files["core/intake/validation.py"]
    assert "domain_logic" in v["roles"]
    assert v["eligible_as_primary"] is True
    assert v["module_name"] == "intake"
    assert set(v["symbols"]) == {"validate_ticket", "ValidationResult"}
    assert v["is_test"] is False and v["is_generated"] is False


def test_entrypoint_role_from_structural_and_module():
    """AC-1: a file in structural.entry_points / modules.primary_entrypoints is an
    entrypoint and eligible."""
    v = _build()["files"]["core/intake/cli.py"]
    assert "entrypoint" in v["roles"]
    assert v["is_entrypoint"] is True
    assert v["eligible_as_primary"] is True


def test_shared_file_is_not_eligible():
    """AC-1/AC-5: a shared file (primary_module null, member_of>1) is never eligible,
    even though it has public symbols (shared wins over domain_logic)."""
    v = _build()["files"]["core/common/paths.py"]
    assert v["eligible_as_primary"] is False
    assert v["module_name"] is None
    assert "shared" in v["roles"]


def test_test_file_not_eligible():
    """AC-1: a test file is is_test and never eligible as primary."""
    v = _build()["files"]["tests/test_validation.py"]
    assert v["is_test"] is True
    assert v["eligible_as_primary"] is False
    assert "test" in v["roles"]


def test_types_file_role():
    """AC-1: a file whose only symbols are type/enum declarations gets the types role."""
    v = _build()["files"]["core/intake/types.py"]
    assert "types" in v["roles"]
    assert v["eligible_as_primary"] is True


def test_generated_file_not_eligible():
    """AC-1: a generated/vendor path is is_generated and never eligible."""
    inv = {"symbols": [
        {"name": "Foo", "kind": "class", "file": "vendor/lib/foo.py", "line": 1,
         "signature": "class Foo", "visibility": "public",
         "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
    ]}
    v = _build(inventory=inv)["files"]["vendor/lib/foo.py"]
    assert v["is_generated"] is True
    assert v["eligible_as_primary"] is False


def test_config_file_not_eligible():
    """AC-1: a config file (by extension) is is_config and not eligible."""
    inv = {"symbols": []}
    modules = {"modules": [{"name": "cfg", "path": "config",
                            "files": ["config/app.yml"]}],
               "files": {"config/app.yml": {"primary_module": "cfg"}}}
    v = fr.build_file_roles(inv, modules, {"entry_points": []})["files"]
    entry = v["config/app.yml"]
    assert entry["is_config"] is True
    assert entry["eligible_as_primary"] is False


def test_membership_via_resolver_not_private_matcher():
    """AC-4: module attribution comes from file_to_module (longest-prefix here)."""
    files = _build()["files"]
    # validation.py resolves to intake via longest-prefix (no files override).
    assert files["core/intake/validation.py"]["module_name"] == "intake"


def test_cli_exit_2_without_inventory(tmp_path):
    """AC-2: fail-closed exit 2 when the required inventory.json is absent."""
    rc = fr.main(["--in-inventory", str(tmp_path / "nope.json"),
                  "--out", str(tmp_path / "roles.json")])
    assert rc == 2


def test_degrade_missing_modules_structural(tmp_path):
    """AC-2: missing optional modules/structural degrade into errors[], not exit 2."""
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps(_INVENTORY), encoding="utf-8")
    out = tmp_path / "roles.json"
    rc = fr.main(["--in-inventory", str(inv),
                  "--in-modules", str(tmp_path / "nope-mod.json"),
                  "--in-structural", str(tmp_path / "nope-struct.json"),
                  "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["errors"]  # degraded, recorded
    assert "core/intake/validation.py" in data["files"]


def test_confidence_reflects_deciding_signal_not_last_rule():
    """AC-1: confidence follows the highest-priority DECIDING signal, independent of
    role-append order. A generated file that ALSO exports public symbols reports the
    generated disqualifier's confidence ('medium' path heuristic), not the
    public_surface role's 'high' — the disqualifier is what fixes eligibility."""
    inv = {"symbols": [
        {"name": "Public", "kind": "class", "file": "vendor/lib/gen.py", "line": 1,
         "signature": "class Public", "visibility": "public",
         "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
    ]}
    v = _build(inventory=inv)["files"]["vendor/lib/gen.py"]
    assert v["is_generated"] is True
    assert "public_surface" in v["roles"]      # the positive role still fired
    assert v["eligible_as_primary"] is False   # but generated disqualifies
    assert v["confidence"] == "medium"         # deciding signal = generated (path)
    # A plain domain-logic file (inventory evidence) stays 'high'.
    dom = _build()["files"]["core/intake/validation.py"]
    assert dom["confidence"] == "high"
    # A shared file is authoritative (membership) → 'high' even though not eligible.
    shared = _build()["files"]["core/common/paths.py"]
    assert shared["confidence"] == "high"
    assert shared["eligible_as_primary"] is False


def test_bare_name_barrel_not_over_confident():
    """FIX-3: a name-only barrel (`__init__.py`) with ZERO symbols and NOT in
    modules.public_surfaces gets public_surface by convention only — confidence must
    NOT be 'high' (high is reserved for inventory/graph/membership evidence)."""
    # __init__.py referenced only via modules.files, no symbols, not a public_surface.
    modules = {"modules": [{"name": "pkg", "path": "pkg",
                            "files": ["pkg/__init__.py"]}],
               "files": {"pkg/__init__.py": {"primary_module": "pkg"}}}
    v = fr.build_file_roles({"symbols": []}, modules, {"entry_points": []})["files"]
    bare = v["pkg/__init__.py"]
    assert "public_surface" in bare["roles"]
    assert bare["confidence"] != "high"       # bare convention → not high
    # A barrel declared a public_surface in modules.json IS high (membership evidence).
    modules2 = {"modules": [{"name": "pkg", "path": "pkg",
                             "public_surfaces": ["pkg/__init__.py"],
                             "files": ["pkg/__init__.py"]}],
                "files": {"pkg/__init__.py": {"primary_module": "pkg"}}}
    v2 = fr.build_file_roles({"symbols": []}, modules2, {"entry_points": []})["files"]
    assert v2["pkg/__init__.py"]["confidence"] == "high"


def test_determinism():
    """AC-8: byte-identical on re-run; no inner timestamp."""
    a = _build()
    b = _build()
    assert json.dumps(a) == json.dumps(b)
    assert "generated_at" not in a
