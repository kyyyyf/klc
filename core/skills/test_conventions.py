#!/usr/bin/env python3
"""test_conventions.py — the ONE answer to "is this path a test?" (KLC-109).

Six-and-then-seven independent copies of this predicate used to live across
``core/skills`` (``tdd_order``, ``test_map``, ``module_edges``, ``file_roles``
reaching into another module's private regex, ``test-writer``'s glob list,
``ac_test_coverage``'s own discovery, ``symbol_usage`` borrowing
``test_map.is_test_file``). This module is the single source every one of
them now reads (AC-1..AC-12, ADR-002 / D-103).

Public surface: ``is_test_path``, ``production_candidates``, ``test_signal``,
``builtin_table``, ``LangRules``, ``table_from_manifest``, ``active_table``.
``is_test_path``/``test_signal`` take an optional ``table=``, an optional
``exists=`` keyword, and an optional ``added=`` keyword (KLC-109 review-fix
round 4, D-109-12); ``production_candidates`` takes only ``table=``. The
DEFAULT call (no ``exists=``, no ``added=``) touches no file, no index and
no git (AC-1).

KLC-109 review-fix round 2 (D-109-9, supersedes D-109-7, code-review HIGH #1
+ HIGH #2): a NAME-signal match — a basename convention hit OUTSIDE any
declared test directory — is trustworthy on its own only when the caller
supplies ``exists=``, a ``str -> bool`` predicate the module calls with each
derived sibling production candidate (a same-directory, repo-relative,
posix-style path). ONE rule covers every consumer:

  - a GATE (``tdd_order.classify``, ``ac_test_coverage``) passes a predicate
    backed by the git object store of the commit(s)/tree it is actually
    classifying — never today's working-tree ``Path.exists()`` against an
    arbitrary, possibly-later checkout (the exact HIGH #2 regression: an
    already-acked step's verdict must not flip because an unrelated LATER
    commit deleted the sibling).
  - an INDEX builder (``test_map``, ``file_roles``, ``module_edges``,
    ``symbol_usage``, ``import-graph``, ``scope_delta``, ``test-writer``)
    passes membership in the KLC-105 file universe it already holds (a set
    lookup — ``set.__contains__`` — genuinely zero I/O, so AC-1's "no
    filesystem I/O" holds unconditionally for every one of these consumers,
    not merely "the default call").
  - a caller that supplies NO ``exists=`` gets the CONSERVATIVE default: a
    basename-only match outside a declared test directory is NOT a test.
    This is the safe failure mode for any future caller that forgets to opt
    in — it can never silently reproduce the self-referential collision
    (``core/skills/test_map.py`` / ``core/skills/test_conventions.py``
    satisfying the bare python ``test_*.py`` glob with no ``map.py``/
    ``conventions.py`` beside them) the way the OLD default (trust the name
    signal unconditionally) did.

KLC-109 review-fix round 4 (D-109-12, supersedes D-109-10, code-review HIGH
round 3): a caller MAY also pass ``added``, a ``str -> bool`` predicate
telling whether the PATH BEING CLASSIFIED (not a sibling candidate) is
newly introduced relative to whatever "before" state the caller is
comparing against — for a gate classifying one commit, "absent from that
commit's own parent tree". When ``added(path)`` is true, a NAME-signal
match needs no confirmed sibling at all: an honestly-committed RED test is
BY CONSTRUCTION added before its production sibling exists, so requiring
the sibling first produced a false, backwards sanction for the ordinary
window between committing a failing test and committing the fix that makes
it pass. ``added=None`` (the default) disables the rule outright — a
caller that never passes it behaves exactly as round 2 (D-109-9) did.

The DIRECTORY signal is unaffected either way — anything under a declared
test directory is a test regardless of ``exists=``/``added=`` (C-001: a
whole test tree must never depend on a sibling-file probe). ``production_candidates`` is
ALSO unaffected: it answers "what production paths would this test file, if
it IS one, pair with", a pattern-shape question the caller resolves against
its own universe (Q-005) — it does not itself confirm a sibling exists, so
adding ``exists=`` support to ``is_test_path``/``test_signal`` changes
nothing about its behaviour or signature.

``active_table()`` is the ONE place a profile's ``test_conventions:``
manifest key is resolved for a real consumer (D-203) — every gate/builder
that wants profile-aware behaviour calls it instead of reading the manifest
itself.

Matching is ``fnmatchcase`` over path segments and the basename only — never
a substring search, never a whole-path regex (AC-3, C-003): ``fnmatchcase``
is mandatory because ``fnmatch()`` normalises case on some platforms, which
could otherwise widen a glob into a substring match.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

_file_dir = Path(__file__).resolve().parent
_FRAMEWORK_ROOT = _file_dir.parent.parent
if str(_file_dir) not in sys.path:
    sys.path.insert(0, str(_file_dir))
import profile_cache  # noqa: E402  (KLC-121: the one profile accessor)


@dataclass(frozen=True)
class LangRules:
    """One language's test-path knowledge. Every field is a tuple so the
    record stays hashable/frozen; ``exts`` is the extension dispatch key —
    the FIRST record whose ``exts`` contains a path's suffix is used."""
    exts: tuple[str, ...]
    test_dirs: tuple[str, ...]                 # path-SEGMENT globs, case-sensitive
    test_basenames: tuple[str, ...]            # basename globs, case-sensitive
    stem_rules: tuple[tuple[str, str], ...]    # (stem glob, replacement template)
    dir_rewrites: tuple[tuple[str, str], ...]  # e.g. ("test", "main") for java
    prod_exts: tuple[str, ...]                 # candidate production extensions


BUILTIN: tuple[LangRules, ...] = (
    LangRules((".py",), ("tests", "test"),
              ("test_*.py", "*_test.py", "conftest.py"),
              (("test_*", "{rest}"), ("*_test", "{head}")), (), (".py",)),
    # KLC-109 review-fix round 2 (D-109-9, code-review HIGH #1): prod_exts
    # covers EVERY js/ts extension this row recognises as a test extension
    # (was: only .ts/.tsx), so a plain-JavaScript colocated test
    # (Foo.spec.js beside Foo.js, x.test.mjs beside x.mjs) can derive its own
    # sibling instead of being silently restricted to the TypeScript pair —
    # the sibling-derivation rule (`_sibling_candidates_same_dir`) always
    # tries the test file's OWN extension first, so `production_candidates`'s
    # ORDER is unaffected for .ts/.tsx callers (AC-4's existing prefix
    # assertions hold — this widening only APPENDS candidates after the test
    # file's own extension, never reorders it). It DOES widen
    # `is_test_path`/`test_signal`'s sibling-existence CONFIRMATION: because
    # every extension in this row shares the SAME `prod_exts` list, a `.ts`/
    # `.tsx` test file can now also be confirmed via a same-stem `.js`/
    # `.jsx`/`.mjs`/`.cjs` sibling with no TypeScript file present at all
    # (review round 3 LOW). This is intentional: a real TypeScript/JavaScript
    # migration project mixes extensions file-by-file, and it can only make
    # `is_test_path` MORE willing to confirm a test, the same direction this
    # row's own widening already loosens for plain JS — see
    # `test_is_test_path_true_for_ts_test_confirmed_by_plain_js_sibling` in
    # tests/test_test_conventions.py, which pins this cross-extension
    # confirmation down as deliberate policy, not an unconsidered side effect.
    LangRules((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"),
              ("__tests__", "tests", "test"), ("*.test.*", "*.spec.*"),
              (("*.test", "{head}"), ("*.spec", "{head}")), (),
              (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")),
    LangRules((".go",), (), ("*_test.go",), (("*_test", "{head}"),), (), (".go",)),
    LangRules((".rs",), ("tests",), ("*_test.rs", "tests.rs", "test.rs"),
              (("*_test", "{head}"),), (), (".rs",)),
    LangRules((".java", ".kt"), ("test", "tests", "androidTest"),
              ("*Test.java", "*Tests.java", "*Test.kt", "*Tests.kt", "*TestCase.java"),
              (("*Tests", "{head}"), ("*Test", "{head}")),
              (("test", "main"),), (".java", ".kt")),
    LangRules((".cs",), ("Tests", "*Tests", "*.Tests", "test"),
              ("*Test.cs", "*Tests.cs"), (("*Tests", "{head}"), ("*Test", "{head}")),
              (), (".cs",)),
    LangRules((".rb",), ("spec", "test"), ("*_spec.rb", "*_test.rb"),
              (("*_spec", "{head}"), ("*_test", "{head}")), (), (".rb",)),
    LangRules((".cpp", ".cc", ".cxx", ".h", ".hpp"),
              ("test", "tests", "Test", "Tests", "*Tests"),
              ("*_test.cpp", "*Test.cpp", "*_test.cc", "*Test.cc"),
              (("*_test", "{head}"), ("*Test", "{head}")), (), (".cpp", ".h")),
)


def builtin_table() -> tuple[LangRules, ...]:
    """The shipped per-language table, with no profile extension applied."""
    return BUILTIN


def _norm(path) -> PurePosixPath:
    return PurePosixPath(str(path).replace("\\", "/"))


def _rules_for(path, table=None) -> LangRules | None:
    tbl = table if table is not None else BUILTIN
    ext = _norm(path).suffix
    if not ext:
        return None
    for r in tbl:
        if ext in r.exts:
            return r
    return None


def _split_basename(name: str) -> tuple[str, str]:
    """(stem, ext) where ext is the LAST dot-suffix, e.g. ``Foo.test.tsx`` ->
    ``("Foo.test", ".tsx")`` — deliberately not ``Path.stem``/``Path.suffix``,
    which would strip only the final component and disagree with the
    ``.test``/``.spec`` stem-rule globs below."""
    idx = name.rfind(".")
    if idx <= 0:
        return name, ""
    return name[:idx], name[idx:]


def _all_test_dirs(table=None) -> frozenset[str]:
    """The UNION of every language's ``test_dirs`` globs. A directory named
    ``tests``/``__tests__``/``spec``/... marks everything under it as test
    territory regardless of a FILE's extension (a YAML/JSON fixture under
    ``tests/fixtures/`` is exactly as much a test artefact as the `.py` file
    beside it) — the directory signal is extension-agnostic by construction,
    unlike the basename signal (a glob like ``*.test.*`` is meaningless
    without knowing which language it belongs to)."""
    tbl = table if table is not None else BUILTIN
    out: set[str] = set()
    for r in tbl:
        out.update(r.test_dirs)
    return frozenset(out)


def _sibling_candidates_same_dir(path, rules) -> list[str]:
    """The same-directory production paths a NAME-signal match derives from
    (KLC-109 review-fix, D-109-9 supersedes D-109-7): strip the convention's
    marker via the row's own ``stem_rules`` to get the production stem, then
    pair it with the row's ``prod_exts`` (the test file's own extension
    first) — the SAME
    directory, never a rewrite or a drop, because a sibling by definition
    lives beside the test file.

    Returns ``[]`` when the basename convention has no derivable stem at all
    (``conftest.py``, ``tests.rs``, ``test.rs``, ...) — those layouts ARE the
    whole test artefact, not a file that pairs with a same-named production
    file one directory over, so no existence check ever applies to them
    ('sibling: none', table-driven via an empty ``stem_rules`` match rather
    than a separate per-row flag)."""
    p = _norm(path)
    segments = list(p.parts[:-1])
    stem, own_ext = _split_basename(p.name)
    stems = _stem_candidates(stem, rules)
    if not stems:
        return []
    exts = ([own_ext] if own_ext in rules.prod_exts else []) + \
           [e for e in rules.prod_exts if e != own_ext]
    out: list[str] = []
    for s in stems:
        for ext in exts:
            cand = "/".join([*segments, s + ext])
            if cand not in out:
                out.append(cand)
    return out


def _shape_signal(path, table=None) -> str | None:
    """'dir' | 'name' | None from PATTERN matching alone — no existence
    check, no ``exists=`` seam, never any I/O. This is the SHAPE question
    ("does this path look like a test, going purely by directory/basename
    convention") that ``production_candidates`` answers (a test file's shape
    determines which production paths it WOULD pair with; confirming that
    one of them actually exists is the caller's job, per Q-005) — kept
    separate from ``test_signal``'s stronger, existence-gated NAME signal so
    widening ``test_signal``'s default (D-109-9) never touches
    ``production_candidates``'s behaviour or signature.

    The DIRECTORY signal is checked against every language's test_dirs
    (extension-agnostic, see ``_all_test_dirs``) BEFORE any extension
    dispatch — so a path with an extension no LangRules record owns (a
    ``.yml``/``.json`` fixture) is still recognised as a test when it lives
    under a recognised test directory. The NAME (basename glob) signal stays
    extension-specific, via the record the path's own extension selects."""
    p = _norm(path)
    segments, base = p.parts[:-1], p.name
    # fnmatchCASE is mandatory: fnmatch() normalises case on Windows and would let
    # `Manifest.cs` match `*Test.cs` — production code classified as a test (AC-3).
    if any(fnmatchcase(s, g) for s in segments for g in _all_test_dirs(table)):
        return "dir"
    rules = _rules_for(path, table)
    if rules is None:
        return None
    if not any(fnmatchcase(base, g) for g in rules.test_basenames):
        return None
    return "name"


def test_signal(path, *, table=None, exists=None, added=None) -> str | None:
    """'dir' | 'name' | None — never raises.

    The DIRECTORY signal (see ``_shape_signal``) is returned unconditionally
    and touches no filesystem (AC-1, C-001: a whole test tree must never
    depend on a sibling-file probe).

    KLC-109 review-fix round 2 (D-109-9, supersedes D-109-7, AC-6/AC-1): a
    NAME-signal match — a basename convention hit OUTSIDE any declared test
    directory — is trustworthy only when the caller supplies ``exists=``, a
    ``str -> bool`` predicate consulted with each same-directory sibling
    production candidate the convention derives (module docstring). CALLING
    WITH NO ``exists=`` IS THE CONSERVATIVE DEFAULT: a basename-only match is
    then NOT a test — never silently trusted the way the OLD default (D-109-7
    and before) trusted it, which is what let the shared module's OWN
    filename (``test_conventions.py``, ``test_map.py`` — a bare python
    ``test_*.py`` glob with no ``conventions.py``/``map.py`` beside it)
    misclassify itself as a test for every consumer that never opted in.
    Every GATE (``tdd_order.classify``, ``ac_test_coverage``) and INDEX
    builder (``test_map``, ``file_roles``, ``module_edges``,
    ``symbol_usage``, ``import-graph``, ``scope_delta``, ``test-writer``)
    now supplies ``exists=`` (module docstring); a caller that does not is
    exercising the safe failure mode, not a supported "trust me" path.

    KLC-109 review-fix round 4 (D-109-12, supersedes D-109-10, code-review
    HIGH round 3): a caller may ALSO supply ``added``, a ``str -> bool``
    predicate telling whether *path itself* is newly introduced relative to
    whatever "before" state the caller compares against (module docstring's
    new-file rule). When both a sibling exists to derive AND ``added(path)``
    is true, the sibling need not be confirmed at all — an honest RED commit
    never has its GREEN sibling yet. ``added=None`` disables the rule."""
    sig = _shape_signal(path, table)
    if sig != "name":
        return sig
    rules = _rules_for(path, table)
    siblings = _sibling_candidates_same_dir(path, rules)
    if not siblings:
        return "name"          # sibling: none — the file IS the whole suite,
                                # regardless of exists=/added= (nothing to confirm)
    if added is not None and added(path):
        return "name"           # freshly added test-shaped file — a RED commit
                                 # needs no sibling yet (D-109-12)
    if exists is None:
        return None             # conservative default — see docstring above
    if any(exists(cand) for cand in siblings):
        return "name"
    return None                 # a pre-existing basename match with no confirmed
                                 # sibling is a bare production commit, not a test


def is_test_path(path, *, table=None, exists=None, added=None) -> bool:
    return test_signal(path, table=table, exists=exists, added=added) is not None


def _dir_variants(segments: list[str], rules: LangRules) -> list[list[str]]:
    """Directory forms of the counterpart, most specific first:
    1. REWRITE — a dir_rewrites pair applied to the FIRST matching segment
       (java  src/test/java/p -> src/main/java/p);
    2. DROP    — the LAST segment matching a test_dirs glob removed
       (python tests/test_x.py -> x.py; js __tests__/Foo.test.ts -> Foo.ts);
    3. SAME    — the directory kept
       (go pkg/foo_test.go -> pkg/foo.go; js Foo.test.tsx -> Foo.tsx).
    A form that does not apply is skipped, never emitted twice."""
    out: list[list[str]] = []
    for src, dst in rules.dir_rewrites:
        if src in segments:
            i = segments.index(src)
            out.append([*segments[:i], dst, *segments[i + 1:]])
            break
    hits = [i for i, s in enumerate(segments)
            if any(fnmatchcase(s, g) for g in rules.test_dirs)]
    if hits:
        out.append([*segments[:hits[-1]], *segments[hits[-1] + 1:]])
    out.append(list(segments))
    seen: set[tuple[str, ...]] = set()
    uniq: list[list[str]] = []
    for d in out:
        if tuple(d) not in seen:
            seen.add(tuple(d))
            uniq.append(d)
    return uniq


def _stem_candidates(stem: str, rules: LangRules) -> list[str]:
    """Stem rules in TABLE ORDER, so `*Tests` is tried before `*Test` and
    `FooTests` yields `Foo`, not `FooTest`. `{head}` is the stem with the
    glob's literal tail removed, `{rest}` the stem with its literal head
    removed."""
    out: list[str] = []
    for pattern, template in rules.stem_rules:
        if not fnmatchcase(stem, pattern):
            continue
        head = stem[: len(stem) - len(pattern.lstrip("*"))] \
            if pattern.startswith("*") else stem
        rest = stem[len(pattern.rstrip("*")):] if pattern.endswith("*") else stem
        value = template.format(head=head, rest=rest, stem=stem)
        if value and value not in out:
            out.append(value)
    return out


def production_candidates(path, *, table=None) -> list[str]:
    """The production paths a test file may pair with, in ONE deterministic order:

        for stem in stem rules (table order; identity stem when the signal was 'dir')
          for dirform in (REWRITE, DROP, SAME)      # rewrite BEFORE drop BEFORE same
            for ext in (the TEST FILE'S OWN ext, *the remaining prod_exts)

    De-duplicated order-preservingly. A non-test or unrecognised path returns [] and
    never raises. The own-extension rule is why `Foo.test.tsx` yields `Foo.tsx` first
    and not `Foo.ts` (AC-4). The caller resolves the candidates against its own file
    universe and never assumes a single answer (Q-005).

    Uses ``_shape_signal`` (pattern only), NOT ``test_signal`` — this answers
    "what would this file, if it IS a test, pair with", independent of
    whether any caller can confirm a sibling exists (D-109-9's ``exists=``
    gate on ``test_signal`` must never narrow this function's candidate
    set)."""
    rules = _rules_for(path, table)
    signal = _shape_signal(path, table)
    if rules is None or signal is None:
        return []
    p = _norm(path)
    segments = list(p.parts[:-1])
    stem, own_ext = _split_basename(p.name)     # "Foo.test", ".tsx"
    stems = _stem_candidates(stem, rules) or ([stem] if signal == "dir" else [])
    exts = ([own_ext] if own_ext in rules.prod_exts else []) + \
           [e for e in rules.prod_exts if e != own_ext]
    out: list[str] = []
    for s in stems:
        for dirform in _dir_variants(segments, rules):
            for ext in exts:
                cand = "/".join([*dirform, s + ext])
                if cand not in out:
                    out.append(cand)
    return out


# --------------------------------------------------------------------------
# Profile extension (KLC-109 step-2, AC-5).
# --------------------------------------------------------------------------

def _strlist(value) -> tuple[str, ...]:
    """Every well-formed string in *value*; anything else (wrong type, a
    non-string entry) is silently dropped — the merge must never raise on
    malformed profile data (AC-5, C-001)."""
    if not isinstance(value, list):
        return ()
    return tuple(v for v in value if isinstance(v, str) and v)


def _pairlist(value) -> tuple[tuple[str, str], ...]:
    """Every well-formed [glob, template] pair in *value*; a malformed entry
    (wrong shape/type) is dropped, never raised on."""
    if not isinstance(value, list):
        return ()
    out: list[tuple[str, str]] = []
    for item in value:
        if (isinstance(item, (list, tuple)) and len(item) == 2
                and isinstance(item[0], str) and isinstance(item[1], str)):
            out.append((item[0], item[1]))
    return tuple(out)


def table_from_manifest(manifest) -> tuple[LangRules, ...]:
    """BUILTIN + a profile's declared extras. Pure, total, never raises: any
    entry that is not a well-formed string (or string pair) is dropped, and a
    key of the wrong type — or one whose every sub-field is schema-invalid —
    degrades to BUILTIN unchanged (AC-5, C-001). Profile rules are APPENDED,
    so a built-in rule keeps its precedence in the D-204 order.

    ``extensions`` (a list of ``.ext`` strings) selects which BUILTIN
    records the extra ``test_dirs``/``test_globs``/``stem_rules`` apply to;
    when omitted, or when a record shares no extension with it, every
    record is extended (so a manifest naming only new dirs/globs still
    reaches every language)."""
    spec = (manifest or {}).get("test_conventions")
    if not isinstance(spec, dict):
        return BUILTIN
    exts = tuple(e for e in _strlist(spec.get("extensions")) if e.startswith("."))
    dirs = _strlist(spec.get("test_dirs"))
    globs = _strlist(spec.get("test_globs"))
    stems = _pairlist(spec.get("stem_rules"))
    if not dirs and not globs and not stems:
        return BUILTIN
    out: list[LangRules] = []
    for r in BUILTIN:
        if exts and not (set(exts) & set(r.exts)):
            out.append(r)
            continue
        out.append(replace(r, test_dirs=r.test_dirs + dirs,
                           test_basenames=r.test_basenames + globs,
                           stem_rules=r.stem_rules + stems))
    return tuple(out)


_ACTIVE: tuple[LangRules, ...] | None = None


def _read_profile_conventions():
    """The parsed `test_conventions:` block of the active profile manifest, or
    None.

    Reads it through `profile_cache.field()` (KLC-121 D-101/D-102) — the
    handed-down payload when a run resolved one, a fresh spawn of
    profile-resolve.py otherwise — so PyYAML never enters the ack gate's
    import chain either way. The bare `except Exception` is deliberate and
    is what C-001 demands: tdd_order.verify_step is a HARD ack block, so no
    profile problem may ever propagate out of here — every failure means
    'use the built-in table'."""
    try:
        raw = profile_cache.field("test_conventions")
        if not raw.strip():
            return None
        return json.loads(raw)
    except Exception:
        return None


def active_table() -> tuple[LangRules, ...]:
    """The ONE profile-table resolution point (D-203, review finding F-2).
    Every gate and builder reads the profile table through THIS function, so
    a layout a profile declares is honoured everywhere or nowhere — never in
    test_map but not in the ack gate. Resolved once per process and cached."""
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = table_from_manifest({"test_conventions": _read_profile_conventions()})
    return _ACTIVE


def _reset_active_table_cache_for_tests() -> None:
    """Test-only escape hatch (design/options.md Q-103): resets the process
    cache so a test can exercise `active_table()` against a different
    profile/manifest without cross-test leakage."""
    global _ACTIVE
    _ACTIVE = None
