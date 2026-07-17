"""KLC-066 step-1 — the single file_to_module() resolver contract (AC-1)."""
import sys
from pathlib import Path

_skills = Path(__file__).parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(_skills))
import module_membership as mm  # noqa: E402


# A modules.json v2 shape: dir-modules, a file-module (stem path), a `files`
# override for an out-of-path file, and a shared file with primary_module=None.
MODULES = {
    "modules": [
        {"name": "core/skills", "path": "core/skills/"},
        {"name": "scope_delta", "path": "core/skills/scope_delta"},
        {"name": "intake", "path": "core/phases/intake"},
        {"name": "routing", "path": "core/routing"},
    ],
    "files": {
        "scripts/intake.py": {"primary_module": "intake"},
        "core/common/paths.py": {"primary_module": None,
                                 "member_of": ["intake", "routing", "core/skills"]},
        "core/skills/validate.py": {"primary_module": "core/skills",
                                    "secondary_modules": ["routing"]},
    },
}


def test_files_override_primary():
    """An out-of-path file with a primary_module override resolves to it."""
    r = mm.file_to_module("scripts/intake.py", MODULES)
    assert r == {"primary_module": "intake", "member_of": ["intake"],
                 "is_shared": False, "resolution_source": "files_override"}


def test_files_override_primary_with_secondary():
    """primary + secondary_modules => member_of is primary first then secondary."""
    r = mm.file_to_module("core/skills/validate.py", MODULES)
    assert r["primary_module"] == "core/skills"
    assert r["member_of"] == ["core/skills", "routing"]
    assert r["is_shared"] is False
    assert r["resolution_source"] == "files_override"


def test_files_override_shared():
    """A shared file (primary None, member_of>1) is is_shared and never orphan."""
    r = mm.file_to_module("core/common/paths.py", MODULES)
    assert r["primary_module"] is None
    assert r["member_of"] == ["intake", "routing", "core/skills"]
    assert r["is_shared"] is True
    assert r["resolution_source"] == "files_override"


def test_longest_prefix_file_module():
    """A file-module path (stem) wins over the parent dir-module via longest prefix."""
    r = mm.file_to_module("core/skills/scope_delta.py", MODULES)
    assert r == {"primary_module": "scope_delta", "member_of": ["scope_delta"],
                 "is_shared": False, "resolution_source": "longest_prefix"}


def test_longest_prefix_dir_module():
    """A plain file under a dir-module resolves to that dir-module."""
    r = mm.file_to_module("core/skills/other.py", MODULES)
    assert r["primary_module"] == "core/skills"
    assert r["resolution_source"] == "longest_prefix"


def test_orphan():
    """A file under no module path and with no override is an explicit orphan."""
    r = mm.file_to_module("docs/readme.md", MODULES)
    assert r == {"primary_module": None, "member_of": [],
                 "is_shared": False, "resolution_source": "orphan"}


def test_boundary_no_stem_sibling_overmatch():
    """FIX-1 (MEDIUM): a file-stem module must NOT swallow a `<stem>-x` sibling.
    Real bug: module `review` (path core/agents/review) over-matched
    core/agents/review-lite.md via raw startswith -> silent scope-creep."""
    md = {"modules": [
        {"name": "core/agents", "path": "core/agents/"},
        {"name": "review", "path": "core/agents/review"},
    ]}
    # the file-module still owns its own .py/.md file (via the "." boundary)
    assert mm.primary_module("core/agents/review.md", md) == "review"
    # but a hyphen-sibling must fall back to the dir-module, never `review`
    r = mm.file_to_module("core/agents/review-lite.md", md)
    assert r["primary_module"] == "core/agents"
    assert r["primary_module"] != "review"


def test_boundary_underscore_sibling_overmatch():
    """Same class for `<stem>_x` siblings."""
    md = {"modules": [
        {"name": "core/skills", "path": "core/skills/"},
        {"name": "scope_delta", "path": "core/skills/scope_delta"},
    ]}
    assert mm.primary_module("core/skills/scope_delta.py", md) == "scope_delta"
    # scope_delta_helper.py must NOT be swallowed by the scope_delta file-module
    assert mm.primary_module("core/skills/scope_delta_helper.py", md) == "core/skills"


def test_dir_module_does_not_match_sibling_file_with_stem():
    """FIX (round 2): a DIRECTORY module (trailing slash) must NOT swallow a
    sibling FILE that shares its stem. `core/agents/` must not match
    `core/agents.py` — the extension boundary applies only to file-stem modules."""
    md = {"modules": [{"name": "core/agents", "path": "core/agents/"}]}
    # files under the directory still match
    assert mm.primary_module("core/agents/x.py", md) == "core/agents"
    # a sibling file sharing the stem must NOT match the directory module
    r = mm.file_to_module("core/agents.py", md)
    assert r["primary_module"] is None
    assert r["resolution_source"] == "orphan"


def test_dir_module_trailing_slash_still_matches():
    """Regression: dir-modules whose path ends in '/' must still match files
    under them (the boundary fix must normalise the trailing slash)."""
    md = {"modules": [{"name": "core/skills", "path": "core/skills/"}]}
    assert mm.primary_module("core/skills/foo.py", md) == "core/skills"
    assert mm.primary_module("core/skills/sub/bar.py", md) == "core/skills"


def test_primary_module_convenience():
    assert mm.primary_module("scripts/intake.py", MODULES) == "intake"
    assert mm.primary_module("core/common/paths.py", MODULES) is None
    assert mm.primary_module("docs/readme.md", MODULES) is None
