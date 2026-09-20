"""module_vocabulary — the one module that answers "is this path infra"
and "what module name does this path have" (KLC-111).

Every producer and every consumer of a module name routes through here, so
there is exactly one vocabulary: the `name` set of the deterministic
`.klc/index/modules.json` UNION the configured infra path entries
(`scope.infra_paths`, KLC-111 AC-1). Nothing here reimplements
`module_membership.file_to_module` — `resolve_name` is a thin, one-line
wrapper over it (AC-5), so a gate's decision for a file and the scope-guard's
decision for that same file can never diverge.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
for _p in (str(_project_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.shared.paths import klc_index_dir  # noqa: E402
import module_membership as _mm  # noqa: E402  (KLC-066: the one resolver)
import settings as _settings  # noqa: E402

# AC-1's mandated default. A trailing slash means a directory prefix; no
# trailing slash means an exact repo-relative file. `.klc/` and `hooks/` and
# the root `README.md` are byte-identical to today's scope_delta literals;
# `.github/` and `.gitlab/` are a deliberate, additive widening (they resolve
# to no module and hard-fail as expansion today) — accepted because it only
# ever REMOVES a hard failure, never adds one (KLC-111 D-202).
INFRA_DEFAULT = (".klc/", "hooks/", ".github/", ".gitlab/", "README.md")

AUDIT_EVENT = "vocabulary-migration"


def infra_paths() -> list[str]:
    """The configured infra list, degrading to `INFRA_DEFAULT` when unset or
    malformed (D-003: the hard default lives here, not in the settings module)."""
    value = _settings.scope_infra_paths()
    if not isinstance(value, list) or not value:
        return list(INFRA_DEFAULT)
    if not all(isinstance(x, str) and x for x in value):
        return list(INFRA_DEFAULT)
    return list(value)


def is_infra(path: str, infra: list[str] | None = None) -> bool:
    """THE infra rule. Trailing slash = directory prefix; otherwise an exact
    repo-relative file. Both of scope_delta's old tuples collapse into this
    one match rule (AC-3)."""
    for entry in (infra if infra is not None else infra_paths()):
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif path == entry:
            return True
    return False


def resolve_name(path: str, modules_data: dict) -> str | None:
    """THE path-to-name rule: one thin wrapper over the KLC-066 resolver, so
    validation and the scope-guard cannot derive different names (AC-5)."""
    return _mm.file_to_module(path, modules_data)["primary_module"]


def module_names(modules_data: dict) -> set[str]:
    """The `name` set of every module in `modules_data` (AC-4)."""
    return {
        m.get("name") for m in (modules_data.get("modules") or [])
        if isinstance(m, dict) and m.get("name")
    }


def vocabulary(modules_data: dict, infra: list[str] | None = None) -> set[str]:
    """The module-name vocabulary: module names UNION infra entries."""
    return module_names(modules_data) | set(infra if infra is not None else infra_paths())


def unknown_names(names, modules_data: dict, infra: list[str] | None = None) -> list[str]:
    """Every non-empty entry in `names` that is outside the vocabulary,
    order preserved. Empty-string entries are not names and are skipped."""
    vocab = vocabulary(modules_data, infra)
    return [n for n in names if n and n not in vocab]


def load_modules(index_dir=None) -> tuple[dict | None, str]:
    """The parsed `modules.json`, or `None` plus a human-readable reason.

    Degrades rather than raises: a missing file, unreadable JSON, a
    non-dict document, or a dict with no `modules` list are all reported
    reasons — never an exception (AC-16)."""
    base = Path(index_dir) if index_dir is not None else klc_index_dir()
    path = base / "modules.json"
    if not path.exists():
        return None, "modules.json not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                              # noqa: BLE001
        return None, f"modules.json unreadable: {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("modules"), list):
        return None, "modules.json has no modules list"
    return data, ""


# --------------------------------------------------------- legacy migration

def tracked_files(modules_data: dict) -> set[str]:
    """The union of every module's tracked file list — the one universe the
    mapper resolves a legacy name's file path or basename stem against."""
    out: set[str] = set()
    for m in modules_data.get("modules") or []:
        if isinstance(m, dict):
            out.update(m.get("files") or [])
    return out


def map_legacy_name(name: str, modules_data: dict) -> dict:
    """One legacy name -> one verdict. Pure in (name, modules_data), so a
    dry-run and the real run agree by construction (D-006).

    Fixed rule order: exact module name, then tracked file path, then a
    UNIQUE basename stem, then directory-prefix ambiguity, then a
    non-unique basename stem (AC-7's own fan-out case), then unmappable —
    `[!DECISION D-111-2]` (review-fix MEDIUM round 1): AC-8 refuses to
    auto-map a name that matches ONLY as a directory prefix, so the
    path/stem checks must run BEFORE the prefix-ambiguity check, not
    after. A name that is BOTH a directory prefix of other modules AND a
    unique path/stem match elsewhere in the tracked-file universe is not
    "only" a prefix hit, so it maps by the stronger, more specific rule
    instead of being refused.
    `[!DECISION D-111-6]` (review-fix MEDIUM round 2) amends D-111-2: the
    override beats prefix-ambiguity ONLY when the stem hit is a SINGLE
    unique module (the tracked-path rule is inherently single-valued —
    `resolve_name` returns one module or `None` — so it needs no such
    guard). A name that is a directory prefix AND a stem match to TWO OR
    MORE unrelated modules is not a precise resolution either, so a
    competing prefix hit wins (`ambiguous`) over the imprecise fan-out.
    With NO competing prefix hit, the non-unique stem fan-out still maps
    (AC-7's own documented behaviour — `intake`/`review`-style fan-out to
    several modules — is unchanged; D-111-6 only changes the outcome for
    the combined case). Returns `{"name", "status", "modules",
    "candidates"}` where `status` is one of `in-vocabulary`, `mapped`,
    `ambiguous`, `unmappable`."""
    if not name:
        return {"name": name, "status": "unmappable", "modules": [], "candidates": []}
    names = module_names(modules_data)
    if name in names:
        return {"name": name, "status": "in-vocabulary", "modules": [name], "candidates": []}
    universe = tracked_files(modules_data)
    if name in universe:
        hit = resolve_name(name, modules_data)
        if hit:
            return {"name": name, "status": "mapped", "modules": [hit], "candidates": []}
    stems = sorted({resolve_name(f, modules_data) for f in universe
                    if Path(f).stem == name} - {None})
    if len(stems) == 1:
        return {"name": name, "status": "mapped", "modules": stems, "candidates": []}
    kids = sorted(m for m in names if m.startswith(name + "/"))
    if kids:
        # A directory prefix is never expanded: a name like `klc-plugin/skills`
        # would fan out to every child module, destroying the very precision
        # the KLC-110 score is meant to measure (AC-8, D-007). A competing
        # non-unique stem match is no more precise, so the prefix hit wins
        # whenever both are present (D-111-6).
        return {"name": name, "status": "ambiguous", "modules": [], "candidates": kids}
    if stems:
        # No competing prefix hit: the non-unique stem fan-out is AC-7's own
        # documented behaviour (e.g. `intake`/`review` mapping to several
        # modules) and is unchanged by D-111-6.
        return {"name": name, "status": "mapped", "modules": stems, "candidates": []}
    return {"name": name, "status": "unmappable", "modules": [], "candidates": []}


def migrate_modules(names, modules_data: dict) -> tuple[list[str], list[dict]]:
    """Rewrite one ticket's `affected_modules` list. Ambiguous and unmappable
    names — and the empty-string boundary case — are carried through
    untouched; duplicates collapse in first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    verdicts: list[dict] = []
    for name in names:
        v = map_legacy_name(name, modules_data)
        verdicts.append(v)
        for m in (v["modules"] or [name]):
            if m not in seen:
                seen.add(m)
                out.append(m)
    return out, verdicts


def vocabulary_share(entry_names, vocab: set[str]) -> dict:
    """`{"entries", "in_vocabulary", "share"}` for a list of
    `affected_modules` entries against a vocabulary set (AC-18). An empty
    entry list reports a share of 1.0 — nothing is out of vocabulary
    because there is nothing to measure."""
    entries = len(entry_names)
    in_vocab = sum(1 for n in entry_names if n in vocab)
    share = (in_vocab / entries) if entries else 1.0
    return {"entries": entries, "in_vocabulary": in_vocab, "share": share}


# ------------------------------------------------------------- nearest name

def _distance(a: str, b: str) -> int:
    """Levenshtein edit distance — a dozen lines of plain code, so no
    dependency is added (D-010)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def nearest(name: str, vocab) -> str | None:
    """Best in-vocabulary candidate for an unknown name, or `None`. Fixed at
    design, not a knob (D-010): (1) a candidate whose last path segment
    equals `name` wins, shallowest then lexicographic — this is what turns
    `phases` into `core/phases`; (2) otherwise the longest candidate sharing
    a `/`-boundary prefix with `name`; (3) otherwise the candidate whose
    last segment is within Levenshtein distance 2, closest then
    lexicographic; (4) otherwise `None`."""
    exact = sorted((c for c in vocab if c.rstrip("/").split("/")[-1] == name),
                   key=lambda c: (c.count("/"), c))
    if exact:
        return exact[0]
    pref = sorted((c for c in vocab
                   if c.startswith(name + "/") or name.startswith(c + "/")),
                  key=lambda c: (-len(c), c))
    if pref:
        return pref[0]
    scored = sorted((_distance(name, c.rstrip("/").split("/")[-1]), c) for c in vocab)
    return scored[0][1] if scored and scored[0][0] <= 2 else None
