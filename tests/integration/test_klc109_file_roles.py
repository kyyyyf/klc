"""tests/integration/test_klc109_file_roles.py — KLC-109 step-7, AC-10: the
file-roles builder computes is_test and its confidence through the shared
test_conventions module's public API — no private attribute of another
module referenced.
"""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILLS = _FW_ROOT / "core" / "skills"
sys.path.insert(0, str(_SKILLS))

import file_roles as fr  # noqa: E402


def test_is_test_and_confidence_computed_via_public_api():
    """AC-10: is_test and its confidence tier come from test_conventions's
    public functions only — a directory-signalled test is 'medium', a
    filename-only test is 'low' (the same tiers as before, now decided by
    test_signal rather than a private regex reach-in)."""
    dir_rec = fr._classify("tests/test_foo.py", [], {}, set(), set())
    assert dir_rec["is_test"] is True
    assert dir_rec["confidence"] == "medium"

    # exists=lambda *_: True per the AC-2 amendment (D-109-9's conservative
    # default requires a confirmed sibling for a basename-only match).
    name_rec = fr._classify("test_bare.py", [], {}, set(), set(), exists=lambda *_: True)
    assert name_rec["is_test"] is True
    assert name_rec["confidence"] == "low"

    prod_rec = fr._classify("core/skills/foo.py", [], {}, set(), set())
    assert prod_rec["is_test"] is False


def test_no_private_attribute_reference_outside_shared_module():
    """AC-10: grepping `_TEST_DIR_RE` anywhere outside
    core/skills/test_conventions.py returns nothing — file_roles.py's former
    reach into test_map._TEST_DIR_RE is gone."""
    hits = []
    for f in sorted(_SKILLS.glob("*.py")):
        if f.name == "test_conventions.py":
            continue
        if "_TEST_DIR_RE" in f.read_text(encoding="utf-8"):
            hits.append(f.name)
    assert hits == [], hits
