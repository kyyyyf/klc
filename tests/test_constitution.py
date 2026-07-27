#!/usr/bin/env python3
"""tests/test_constitution.py — the constitution's two forms stay in lockstep.

KLC-082 ships the project constitution as two coupled artifacts: the narrative
`docs/constitution.md` and the machine form `config/constitution.yml` (read by
`core/skills/constitution.py`). These tests are the guardrail that keeps them
honest: the YAML is well-formed under the SAME parser the runtime uses, every
principle carries the full schema, ids are unique stable slugs, and the id set in
the YAML matches the id set in the Markdown exactly (no principle documented but
unlisted, none listed but undocumented).

Run:  python -m pytest tests/test_constitution.py -v
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import constitution  # noqa: E402  (the loader under test)
import _yaml  # noqa: E402  (the real runtime parser)

YML = FW_ROOT / "config" / "constitution.yml"
MD = FW_ROOT / "docs" / "constitution.md"

CATEGORIES = {"architecture", "boundary", "process", "product", "governance"}
CHECKS = {"deterministic", "review"}
STATUSES = {"upheld", "open-gap"}
BASE_KEYS = {"id", "category", "check", "statement", "status"}
# A deterministic entry must ALSO ship an executable predicate so 083 does not
# reconstruct it from prose: a target, a command, and at least one of a token
# denylist / path pattern, plus the expected passing outcome.
DET_KEYS = BASE_KEYS | {"check_target", "check_command", "check_expect"}
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Every principle in the .md is a level-3 heading holding its id in backticks:
#   ### `single-source-of-truth`
MD_HEADING = re.compile(r"^### `([a-z0-9-]+)`\s*$", re.MULTILINE)


def _yml_principles() -> list[dict]:
    """Parse the YAML with the in-repo minimal parser (what the runtime uses)."""
    doc = _yaml.parse(YML.read_text(encoding="utf-8"))
    return doc["principles"]


# --- the file is well-formed -------------------------------------------------

def test_files_exist_and_nonempty():
    assert YML.exists() and YML.stat().st_size > 0
    assert MD.exists() and MD.stat().st_size > 0


def test_yaml_well_formed_under_both_parsers():
    """The minimal in-repo parser and PyYAML must AGREE — so the file is valid
    standard YAML AND consumable by the stdlib-only runtime path."""
    import yaml  # dev/test dependency only

    minimal = _yaml.parse(YML.read_text(encoding="utf-8"))
    standard = yaml.safe_load(YML.read_text(encoding="utf-8"))
    assert minimal == standard
    assert isinstance(minimal.get("principles"), list)
    assert minimal["principles"], "constitution has no principles"


# --- every principle carries the full schema ---------------------------------

def test_every_principle_has_full_schema():
    for p in _yml_principles():
        assert isinstance(p["id"], str) and p["id"]
        assert isinstance(p["statement"], str) and p["statement"].strip()
        assert p["category"] in CATEGORIES, p
        assert p["check"] in CHECKS, p
        assert p["status"] in STATUSES, p
        if p["check"] == "review":
            # review principles carry exactly the base schema, no predicate.
            assert set(p) == BASE_KEYS, p
        else:
            # deterministic principles carry the base schema PLUS an executable
            # predicate (a token denylist or a path pattern).
            assert DET_KEYS.issubset(set(p)), p
            assert p["check_tokens"] if "check_tokens" in p else p.get("check_pattern"), p
            assert ("check_tokens" in p) or ("check_pattern" in p), p
            assert isinstance(p["check_command"], str) and p["check_command"].strip()
            assert isinstance(p["check_target"], str) and p["check_target"].strip()


def test_ids_are_unique_stable_slugs():
    ids = [p["id"] for p in _yml_principles()]
    assert len(ids) == len(set(ids)), "duplicate principle id"
    for pid in ids:
        assert SLUG.match(pid), f"id is not a kebab-case slug: {pid!r}"


def test_at_least_one_of_each_check_type():
    checks = {p["check"] for p in _yml_principles()}
    # The design splits mechanical gates (083) from judgment calls (084); both
    # kinds must actually be present or the split is vacuous.
    assert "review" in checks
    assert "deterministic" in checks


# --- md <-> yml parity (the lockstep invariant) ------------------------------

def test_md_yml_id_parity():
    yml_ids = {p["id"] for p in _yml_principles()}
    md_ids = set(MD_HEADING.findall(MD.read_text(encoding="utf-8")))
    missing_in_md = yml_ids - md_ids
    extra_in_md = md_ids - yml_ids
    assert not missing_in_md, f"ids in yml but not documented in md: {sorted(missing_in_md)}"
    assert not extra_in_md, f"ids documented in md but not in yml: {sorted(extra_in_md)}"


# --- the loader under test ---------------------------------------------------

def test_loader_matches_file():
    loaded = constitution.load()
    assert [p["id"] for p in loaded] == [p["id"] for p in _yml_principles()]
    assert constitution.ids() == [p["id"] for p in loaded]


def test_loader_by_id_and_partitions():
    ids = constitution.ids()
    # by_id round-trips for a known id and returns None for an unknown one.
    assert constitution.by_id(ids[0])["id"] == ids[0]
    assert constitution.by_id("no-such-principle") is None
    # deterministic + review partition the whole list with no overlap.
    det = {p["id"] for p in constitution.deterministic()}
    rev = {p["id"] for p in constitution.review()}
    assert det.isdisjoint(rev)
    assert det | rev == set(ids)


# --- the deterministic predicates actually hold ------------------------------

def _run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=FW_ROOT, shell=True, capture_output=True, text=True
    )


def test_klc_state_not_tracked_predicate_passes():
    """The one deterministic principle's `.klc`-on-code-branch grep must find
    nothing (exit 1). Its `^.klc/` pattern is a path prefix that is safe to ship
    anywhere, so it can legitimately be a deterministic check in a mirrored file."""
    p = constitution.by_id("klc-state-not-tracked-on-main")
    assert p["check"] == "deterministic"
    assert p["status"] == "upheld"
    r = _run(p["check_command"])
    # grep exits 1 when there is NO match — that is the passing (clean) outcome.
    assert r.returncode == 1, f"unexpected .klc tracking: {r.stdout!r}"


def test_exactly_one_deterministic_principle():
    det = [p["id"] for p in _yml_principles() if p["check"] == "deterministic"]
    assert det == ["klc-state-not-tracked-on-main"], det


# --- the constitution is itself safe to mirror -------------------------------

# Built from fragments so THIS test file ships no literal internal token either
# (it is mirrored to the public remote too). Matches the internal git host and the
# corporate domain that must never appear in the public constitution.
_INTERNAL_TOKEN_RE = re.compile("war" "gaming" "|" "git" "lab[.]rnd", re.IGNORECASE)


def test_constitution_files_carry_no_internal_tokens():
    """`public-mirror-no-internal-refs` is enforced origin-side precisely BECAUSE a
    denylist cannot live on the surface it guards. Guard that the constitution's own
    two files (which are mirrored to the public remote) contain no literal internal
    identifier — otherwise KLC-082 would itself leak onto the mirror and any future
    gh-side grep would self-trip on this very file."""
    for path in (YML, MD):
        text = path.read_text(encoding="utf-8")
        hits = _INTERNAL_TOKEN_RE.findall(text)
        assert not hits, f"{path.name} ships a literal internal token: {hits}"


# --- the reader is package-safe (codex P2) -----------------------------------

def test_reader_is_package_safe():
    """Under a package-style import (`core.skills.constitution`) `core/skills`
    is not on sys.path, so a naive `import _yaml` would resolve to PyYAML's C
    accelerator (no `parse`). Load the module by path under that dotted name with
    `core/skills` removed, and assert the reader still works."""
    skills = str(FW_ROOT / "core" / "skills")
    saved = list(sys.path)
    try:
        sys.path[:] = [p for p in sys.path if p != skills]
        if str(FW_ROOT) not in sys.path:
            sys.path.insert(0, str(FW_ROOT))
        spec = importlib.util.spec_from_file_location(
            "core.skills.constitution", FW_ROOT / "core" / "skills" / "constitution.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.ids() == [p["id"] for p in _yml_principles()]
        assert {p["id"] for p in mod.deterministic()} == {
            p["id"] for p in _yml_principles() if p["check"] == "deterministic"
        }
    finally:
        sys.path[:] = saved
