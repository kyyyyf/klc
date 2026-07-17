"""KLC-066 coordination-fuzz-gate — permanent regression gate proving there is
exactly ONE module set.

The scope_delta -> ack path means a bug in file_to_module() silently corrupts
review/integrate acceptance for EVERY ticket, so two hand-picked fixtures are not
enough. This gate GENERATES many randomized modules.json maps (out-of-path files,
shared/multi-module files, orphans, overlapping/nested path prefixes, empty
modules, file-stem paths) and asserts, for each map, that every migrated consumer
attributes files to exactly the module set that the single file_to_module()
resolver does. If anyone reintroduces a private longest-prefix copy, a consumer
diverges and this gate fails.

Invariants asserted per generated map:
  I1 one-source-of-truth (membership): diff-modules, public-api-filter,
     context-loader, update stale all attribute each file to file_to_module()'s
     member_of — no divergent set.
  I2 one-source-of-truth (primary): module_edges attributes each edge endpoint to
     file_to_module()'s primary_module.
  I3 scope_delta bucketing: an owned file -> owned (expansion path); a shared file
     -> shared_touched (drift path); an orphan -> unknown (expansion path).
  I4 determinism: file_to_module() is byte-identical on re-run.
  I5 context-loader parity: context-loader's membership view == the resolver.
"""
import importlib.util
import json
import random
import sys
from pathlib import Path

_skills = Path(__file__).parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(_skills))
import module_membership as mm  # noqa: E402
import module_edges as me  # noqa: E402
import scope_delta as sd  # noqa: E402


def _load(stem):
    """Import a hyphenated skill by file path."""
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


# --------------------------------------------------------------------------- #
# random map generator
# --------------------------------------------------------------------------- #

def _gen_map(rng):
    """Return (modules_data, files) — a plausibly-adversarial modules.json v2."""
    n = rng.randint(1, 8)
    names, modules = [], []
    used_paths = set()
    for i in range(n):
        name = f"mod{i}"
        names.append(name)
        # Mix dir-paths ("a/b/"), file-stem paths ("a/b/c"), nested & overlapping.
        style = rng.choice(["dir", "stem", "nested", "empty"])
        if style == "empty":
            path = ""
        elif style == "dir":
            path = f"src/pkg{rng.randint(0,3)}/"
        elif style == "stem":
            path = f"src/pkg{rng.randint(0,3)}/file{i}"
        else:
            path = f"src/pkg{rng.randint(0,3)}/sub{rng.randint(0,2)}/deep{i}"
        # allow duplicate paths sometimes to stress tie-breaks
        if path in used_paths and rng.random() < 0.5:
            path = path + f"x{i}"
        used_paths.add(path)
        # Real modules.json carries a per-module `files` list; populate it so the
        # update stale-detector's >20%-changed fallback (which divides by the
        # total tracked-file count) does not trip in the fuzz harness.
        modules.append({"name": name, "path": path,
                        "files": [f"{(path or name).rstrip('/')}/track{k}.py"
                                  for k in range(10)],
                        "depends_on": [], "depended_by": []})

    files_map = {}
    universe = []
    # files that fall under some module path (longest-prefix territory)
    for m in modules:
        if m["path"]:
            base = m["path"].rstrip("/")
            for j in range(rng.randint(0, 3)):
                universe.append(f"{base}/f{j}.py")
            universe.append(f"{base}.py")  # file-stem sibling
    # out-of-path override files
    for k in range(rng.randint(0, 3)):
        f = f"scripts/tool{k}.py"
        files_map[f] = {"primary_module": rng.choice(names)}
        universe.append(f)
    # shared files (primary None, member_of >= 1)
    for k in range(rng.randint(0, 3)):
        f = f"common/shared{k}.py"
        members = rng.sample(names, rng.randint(1, len(names)))
        files_map[f] = {"primary_module": None, "member_of": members}
        universe.append(f)
    # pure orphans
    for k in range(rng.randint(0, 3)):
        universe.append(f"orphan/zzz{k}_{rng.randint(0,999)}.md")

    md = {"modules": modules, "files": files_map}
    # dedupe universe, keep deterministic order
    seen, uniq = set(), []
    for f in universe:
        if f not in seen:
            seen.add(f); uniq.append(f)
    return md, uniq


# --------------------------------------------------------------------------- #
# expected attributions, computed ONLY from the resolver
# --------------------------------------------------------------------------- #

def _members(f, md):
    return set(mm.file_to_module(f, md)["member_of"])


def _valid_names(md):
    return {m["name"] for m in md["modules"]}


# --------------------------------------------------------------------------- #
# invariants
# --------------------------------------------------------------------------- #

def _check_diff_modules(md, files, tmp):
    diff = tmp / "d.patch"
    diff.write_text("".join(f"+++ b/{f}\n" for f in files), encoding="utf-8")
    got = set(dm.affected_modules(diff, md))
    expected = set().union(*[_members(f, md) for f in files]) if files else set()
    assert got == expected, f"diff-modules diverged: {got} != {expected}"


def _check_public_api_filter(md, files):
    inv = {"symbols": {"python": {"items": [
        {"file": f, "name": f"sym_{i}", "kind": "function",
         "signature": f"def sym_{i}(): pass"}
        for i, f in enumerate(files)
    ]}}}
    mods_copy = json.loads(json.dumps(md))
    _, _, sbm = paf.trim_modules(inv, mods_copy, cap=999)
    for i, f in enumerate(files):
        want = _members(f, md)
        for name in _valid_names(md):
            present = any(it["name"] == f"sym_{i}" for it in sbm.get(name, []))
            assert present == (name in want), (
                f"public-api-filter diverged for {f}->{name}")


def _check_context_loader(md, files):
    inv = {"symbols": {"python": {"items": [
        {"file": f, "name": f"cl_{i}", "kind": "function", "signature": "x"}
        for i, f in enumerate(files)
    ]}}}
    idx = cl._build_symbols_by_module_from_inventory(inv, md)
    for i, f in enumerate(files):
        want = _members(f, md)
        for name in _valid_names(md):
            present = any(it["name"] == f"cl_{i}" for it in idx.get(name, []))
            assert present == (name in want), (
                f"context-loader diverged for {f}->{name}")


def _check_update_stale(md, files, tmp):
    idx = tmp / "idx"
    idx.mkdir(exist_ok=True)
    # depended_by empty + <20% changed keeps closure/fallback no-ops so stale
    # equals the direct file->module attribution.
    (idx / "modules.json").write_text(json.dumps(md), encoding="utf-8")
    pick = files[:1]  # one file → far under the 20% fallback threshold
    if not pick:
        return
    got = set(upd._compute_stale(idx, pick)["stale_modules"])
    expected = set().union(*[_members(f, md) for f in pick])
    assert got == expected, f"update stale diverged: {got} != {expected}"


def _check_module_edges(md, files, rng):
    if len(files) < 2:
        return
    edges = []
    for _ in range(rng.randint(1, 6)):
        a, b = rng.choice(files), rng.choice(files)
        edges.append({"from": a, "to": b})
    depgraph = {"import_graphs": {"python": {"edges": edges}}}
    result = me.aggregate_module_edges(md, depgraph)
    by_name = {m["name"]: m for m in result["modules"]}
    exp_dep, exp_by = {}, {}
    for e in edges:
        sm = mm.file_to_module(e["from"], md)["primary_module"]
        tm = mm.file_to_module(e["to"], md)["primary_module"]
        if sm and tm and sm != tm:
            exp_dep.setdefault(sm, set()).add(tm)
            exp_by.setdefault(tm, set()).add(sm)
    for name in _valid_names(md):
        assert set(by_name[name]["depends_on"]) == exp_dep.get(name, set()), \
            f"module_edges depends_on diverged for {name}"
        assert set(by_name[name]["depended_by"]) == exp_by.get(name, set()), \
            f"module_edges depended_by diverged for {name}"


def _check_scope_delta(md, files):
    owned, shared, unknown = sd._bucket_changed(files, md)
    exp_owned, exp_shared, exp_unknown = set(), set(), []
    for f in files:
        r = mm.file_to_module(f, md)
        if r["is_shared"]:
            exp_shared.update(r["member_of"])
        elif r["primary_module"]:
            exp_owned.add(r["primary_module"])
        else:
            exp_unknown.append(f)
    assert owned == sorted(exp_owned)
    assert shared == sorted(exp_shared)
    assert unknown == sorted(exp_unknown)


def _check_determinism(md, files):
    for f in files:
        a = mm.file_to_module(f, md)
        b = mm.file_to_module(f, md)
        assert a == b


ROUNDS = 300


def test_fuzz_one_source_of_truth(tmp_path):
    """300 randomized maps; every consumer agrees with file_to_module()."""
    for seed in range(ROUNDS):
        rng = random.Random(seed)
        md, files = _gen_map(rng)
        _check_determinism(md, files)                     # I4
        _check_scope_delta(md, files)                     # I3
        _check_diff_modules(md, files, tmp_path)          # I1
        _check_public_api_filter(md, files)               # I1
        _check_context_loader(md, files)                  # I1 / I5
        _check_update_stale(md, files, tmp_path)          # I1
        _check_module_edges(md, files, rng)               # I2


# --------------------------------------------------------------------------- #
# independent CORRECTNESS oracle (FIX-3)
#
# The 300-map fuzz proves CONSISTENCY (every consumer agrees with the resolver)
# but computes "expected" from the resolver itself, so a resolver that
# over-matches would make every consumer over-match identically and still
# "agree" — that is exactly why the fuzz missed the review/review-lite bug. These
# cases hard-author the RIGHT answer WITHOUT calling the resolver, so a wrong
# resolver fails here even if all consumers stay mutually consistent.
# --------------------------------------------------------------------------- #

# (modules_data, file, expected_primary, expected_source, expected_is_shared)
_ORACLE = [
    # boundary: `review` must NOT swallow the `review-lite.md` sibling
    ({"modules": [{"name": "core/agents", "path": "core/agents/"},
                  {"name": "review", "path": "core/agents/review"}]},
     "core/agents/review-lite.md", "core/agents", "longest_prefix", False),
    # ... but `review` DOES own its own review.md via the extension boundary
    ({"modules": [{"name": "core/agents", "path": "core/agents/"},
                  {"name": "review", "path": "core/agents/review"}]},
     "core/agents/review.md", "review", "longest_prefix", False),
    # underscore sibling must not be swallowed by the file-stem module
    ({"modules": [{"name": "core/skills", "path": "core/skills/"},
                  {"name": "scope_delta", "path": "core/skills/scope_delta"}]},
     "core/skills/scope_delta_helper.py", "core/skills", "longest_prefix", False),
    # dir-module (trailing slash) must NOT swallow a sibling FILE sharing its stem
    ({"modules": [{"name": "core/agents", "path": "core/agents/"}]},
     "core/agents.py", None, "orphan", False),
    # ... but the same dir-module DOES own files under it
    ({"modules": [{"name": "core/agents", "path": "core/agents/"}]},
     "core/agents/x.py", "core/agents", "longest_prefix", False),
    # file-stem module owns its own .py
    ({"modules": [{"name": "core/skills", "path": "core/skills/"},
                  {"name": "scope_delta", "path": "core/skills/scope_delta"}]},
     "core/skills/scope_delta.py", "scope_delta", "longest_prefix", False),
    # dir-module with trailing slash still matches nested files
    ({"modules": [{"name": "core/skills", "path": "core/skills/"}]},
     "core/skills/sub/deep.py", "core/skills", "longest_prefix", False),
    # root-level file resolves ONLY via an explicit files override (FIX-2)
    ({"modules": [{"name": ".", "path": ""}],
      "files": {"main.py": {"primary_module": "."}}},
     "main.py", ".", "files_override", False),
    # root-level file WITHOUT an override is an orphan (documents FIX-2's need)
    ({"modules": [{"name": ".", "path": ""}]},
     "main.py", None, "orphan", False),
    # a shared file is is_shared and belongs to all its members
    ({"modules": [{"name": "a", "path": "a"}, {"name": "b", "path": "b"}],
      "files": {"common/x.py": {"primary_module": None, "member_of": ["a", "b"]}}},
     "common/x.py", None, "files_override", True),
    # nested paths: the deeper module wins
    ({"modules": [{"name": "a", "path": "src/a"},
                  {"name": "a/b", "path": "src/a/b"}]},
     "src/a/b/f.py", "a/b", "longest_prefix", False),
    # pure orphan
    ({"modules": [{"name": "a", "path": "src/a"}]},
     "docs/readme.md", None, "orphan", False),
]


def test_resolver_correctness_oracle():
    """Hand-authored right answers (computed WITHOUT the resolver) — catches an
    over-matching resolver that the consistency fuzz cannot see."""
    for md, f, exp_primary, exp_source, exp_shared in _ORACLE:
        r = mm.file_to_module(f, md)
        assert r["primary_module"] == exp_primary, (
            f"{f}: primary {r['primary_module']} != {exp_primary}")
        assert r["resolution_source"] == exp_source, (
            f"{f}: source {r['resolution_source']} != {exp_source}")
        assert r["is_shared"] == exp_shared, f"{f}: is_shared mismatch"


def test_oracle_would_catch_raw_startswith_regression():
    """Guard the guard: a naive raw-startswith resolver MUST fail the oracle
    (proves the oracle is not vacuous and pins the FIX-1 regression class)."""
    def raw_startswith(path, md):
        best, bl = None, -1
        for m in md.get("modules", []):
            p = m.get("path") or ""
            if p and path.startswith(p) and len(p) > bl:
                bl, best = len(p), m["name"]
        return best
    # the review-lite oracle case: raw startswith returns the WRONG answer
    md = _ORACLE[0][0]
    assert raw_startswith("core/agents/review-lite.md", md) == "review"   # the bug
    assert mm.primary_module("core/agents/review-lite.md", md) == "core/agents"  # fixed

    # and the round-2 strip-and-unify variant over-matches the OTHER way: a
    # dir-module swallowing a sibling file via the extension branch.
    def strip_and_unify(path, md):
        best, bl = None, -1
        for m in md.get("modules", []):
            p = (m.get("path") or "").rstrip("/")
            if p and (path == p or path.startswith(p + "/") or path.startswith(p + ".")) \
                    and len(p) > bl:
                bl, best = len(p), m["name"]
        return best
    dir_md = {"modules": [{"name": "core/agents", "path": "core/agents/"}]}
    assert strip_and_unify("core/agents.py", dir_md) == "core/agents"   # the round-2 bug
    assert mm.primary_module("core/agents.py", dir_md) is None          # fixed


def test_fuzz_covers_all_shapes():
    """Sanity: the generator actually emits shared files, orphans, overrides,
    and file-stem resolution across the rounds (so the gate isn't vacuous)."""
    saw_shared = saw_orphan = saw_override = saw_stem = False
    for seed in range(ROUNDS):
        md, files = _gen_map(random.Random(seed))
        for f in files:
            r = mm.file_to_module(f, md)
            saw_shared |= r["is_shared"]
            saw_orphan |= (r["resolution_source"] == "orphan")
            saw_override |= (r["resolution_source"] == "files_override")
            saw_stem |= (r["resolution_source"] == "longest_prefix"
                         and r["primary_module"] is not None)
    assert saw_shared and saw_orphan and saw_override and saw_stem
