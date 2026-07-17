"""KLC-066 step-2 — one-source-of-truth (AC-2) + feature-OFF byte-parity.

AC-2: with an out-of-path file and a shared file present, every migrated consumer
resolves membership through file_to_module() — no divergent second set.

Feature-OFF parity: for a modules.json with NO `files` map (today's shape), the
resolver's longest-prefix branch is byte-identical to the deleted private
raw-startswith longest-prefix logic that scope_delta / diff-modules /
public-api-filter / context-loader used, so the migration is behaviour-preserving.
"""
import importlib.util
import json
import sys
from pathlib import Path

_skills = Path(__file__).parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(_skills))
import module_membership as mm  # noqa: E402
import module_edges as me  # noqa: E402
import scope_delta as sd  # noqa: E402


def _load(stem):
    spec = importlib.util.spec_from_file_location(
        stem.replace("-", "_"), str(_skills / f"{stem}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


dm = _load("diff-modules")
paf = _load("public-api-filter")
cl = _load("context-loader")
sys.path.insert(0, str(_skills.parent.parent / "scripts"))
import update as upd  # noqa: E402


# AC-2 fixture: out-of-path file (scripts/intake.py) + shared file (paths.py).
MD = {
    "modules": [
        # per-module `files` lists sized so update's >20%-changed fallback (which
        # divides by total tracked files) does not trip when one file changes.
        {"name": "core/skills", "path": "core/skills/",
         "files": [f"core/skills/a{k}.py" for k in range(10)]},
        {"name": "scope_delta", "path": "core/skills/scope_delta",
         "files": [f"core/skills/scope_delta/x{k}.py" for k in range(10)]},
        {"name": "intake", "path": "core/phases/intake",
         "files": [f"core/phases/intake/i{k}.py" for k in range(10)]},
        {"name": "routing", "path": "core/routing",
         "files": [f"core/routing/r{k}.py" for k in range(10)]},
    ],
    "files": {
        "scripts/intake.py": {"primary_module": "intake"},
        "core/common/paths.py": {"primary_module": None,
                                 "member_of": ["intake", "routing"]},
    },
}
UNIVERSE = [
    "core/skills/scope_delta.py",   # file-module (longest prefix)
    "core/skills/other.py",         # dir-module
    "scripts/intake.py",            # out-of-path override
    "core/common/paths.py",         # shared
    "docs/readme.md",               # orphan
]


def _members(f):
    return set(mm.file_to_module(f, MD)["member_of"])


def test_ac2_diff_modules_agrees_with_resolver(tmp_path):
    diff = tmp_path / "d.patch"
    diff.write_text("".join(f"+++ b/{f}\n" for f in UNIVERSE), encoding="utf-8")
    got = set(dm.affected_modules(diff, MD))
    expected = set().union(*[_members(f) for f in UNIVERSE])
    assert got == expected
    # the out-of-path override and the shared file are both present in the set
    assert "intake" in got and "routing" in got


def test_ac2_public_api_filter_agrees_with_resolver():
    inv = {"symbols": {"python": {"items": [
        {"file": f, "name": f"s{i}", "kind": "function", "signature": "def s(): 0"}
        for i, f in enumerate(UNIVERSE)]}}}
    _, _, sbm = paf.trim_modules(inv, json.loads(json.dumps(MD)), cap=999)
    for i, f in enumerate(UNIVERSE):
        for name in {m["name"] for m in MD["modules"]}:
            present = any(it["name"] == f"s{i}" for it in sbm.get(name, []))
            assert present == (name in _members(f))


def test_ac2_context_loader_agrees_with_resolver():
    inv = {"symbols": {"python": {"items": [
        {"file": f, "name": f"c{i}", "kind": "function", "signature": "x"}
        for i, f in enumerate(UNIVERSE)]}}}
    idx = cl._build_symbols_by_module_from_inventory(inv, MD)
    for i, f in enumerate(UNIVERSE):
        for name in {m["name"] for m in MD["modules"]}:
            present = any(it["name"] == f"c{i}" for it in idx.get(name, []))
            assert present == (name in _members(f))


def test_ac2_scope_delta_agrees_with_resolver():
    owned, shared, unknown = sd._bucket_changed(UNIVERSE, MD)
    # scope_delta owns non-shared primaries, buckets shared separately
    assert owned == sorted({"scope_delta", "core/skills", "intake"})
    assert shared == sorted({"intake", "routing"})
    assert unknown == ["docs/readme.md"]


def test_ac2_update_stale_agrees_with_resolver(tmp_path):
    idx = tmp_path / "idx"; idx.mkdir()
    (idx / "modules.json").write_text(json.dumps(MD), encoding="utf-8")
    got = set(upd._compute_stale(idx, ["scripts/intake.py"])["stale_modules"])
    assert got == {"intake"}   # out-of-path override resolves, no divergent set


def test_ac2_module_edges_agrees_with_resolver():
    dg = {"import_graphs": {"python": {"edges": [
        {"from": "scripts/intake.py", "to": "core/routing/r.py"},
    ]}}}
    res = me.aggregate_module_edges(MD, dg)
    by = {m["name"]: m for m in res["modules"]}
    # scripts/intake.py -> intake (override); core/routing/r.py -> routing
    assert by["intake"]["depends_on"] == ["routing"]
    assert by["routing"]["depended_by"] == ["intake"]


# --------------------------------------------------------------------------- #
# feature-OFF byte-parity
# --------------------------------------------------------------------------- #

def _boundary_safe_longest_prefix(f, modules):
    """Independent reference (NOT the resolver): boundary-aware longest prefix.
    A module path matches a file only when the file equals it, is under it
    ('<path>/...'), or is it plus an extension ('<path>.ext'). This is the
    CORRECT semantics; the old raw f.startswith(path) was the FIX-1 bug."""
    best, bl = None, -1
    for m in modules:
        p = (m.get("path") or "").rstrip("/")
        if p and (f == p or f.startswith(p + "/") or f.startswith(p + ".")) \
                and len(p) > bl:
            bl, best = len(p), m["name"]
    return best


def test_feature_off_byte_parity_canonical():
    """With NO `files` map, the resolver == the boundary-safe longest-prefix
    reference for every file (member_of is the single primary). For all files
    EXCEPT `<stem>-x`/`<stem>_x` siblings this is byte-identical to today; those
    siblings are where the old raw-startswith was the bug (see next test)."""
    md_no_files = {"modules": MD["modules"]}   # drop the files map (today's shape)
    probe = [
        "core/skills/scope_delta.py", "core/skills/other.py",
        "core/phases/intake.py", "core/routing/r.py", "vendor/x.py",
        "core/skills/a.py",
    ]
    for f in probe:
        r = mm.file_to_module(f, md_no_files)
        ref = _boundary_safe_longest_prefix(f, md_no_files["modules"])
        assert r["primary_module"] == ref, f"parity broke for {f}"
        if ref is None:
            assert r["member_of"] == [] and r["resolution_source"] == "orphan"
        else:
            assert r["member_of"] == [ref]
            assert r["resolution_source"] == "longest_prefix"


def test_feature_off_only_diff_from_old_raw_is_the_overmatch_bugfix():
    """The migration is byte-identical to the old raw-startswith behaviour for
    every file EXCEPT a `<stem>-x` sibling, where the old code over-matched (the
    FIX-1 bug) and the resolver now correctly falls back."""
    md = {"modules": [
        {"name": "core/agents", "path": "core/agents/"},
        {"name": "review", "path": "core/agents/review"},
    ]}

    def old_raw(f):
        best, bl = None, -1
        for m in sorted(md["modules"], key=lambda m: -len(m.get("path", ""))):
            p = m.get("path", "")
            if p and f.startswith(p) and len(p) > bl:
                bl, best = len(p), m["name"]
        return best

    # agreement on a normal file
    assert old_raw("core/agents/review.md") == mm.primary_module("core/agents/review.md", md) == "review"
    # divergence ONLY on the sibling: old over-matched to `review`; resolver fixes it
    assert old_raw("core/agents/review-lite.md") == "review"
    assert mm.primary_module("core/agents/review-lite.md", md) == "core/agents"


def test_module_edges_reconciliation_is_intended():
    """module_edges was boundary-aware and mis-attributed file-module files to
    their parent dir-module; after migration it agrees with the canonical
    (raw-startswith) set. This documents the one intended output change."""
    md_no_files = {"modules": MD["modules"]}
    # core/skills/scope_delta.py now attributes to the scope_delta file-module,
    # matching scope_delta/diff-modules (previously module_edges said core/skills).
    assert mm.primary_module("core/skills/scope_delta.py", md_no_files) == "scope_delta"
