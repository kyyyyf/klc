#!/usr/bin/env python3
"""planning-retriever.py — query-time planning retriever (KLC-068).

The **query-time capstone** of the planning index (planning_indexer.md
§"Query-time: retriever, а не статический router"). It turns a feature
description into a ranked, explainable project slice and materialises it per
ticket as ``.klc/scratch/<KEY>/retrieval_trace.json``.

It consumes the merged planning views — ``modules.json`` v2 (KLC-066),
``file_roles.json`` / ``symbol_usage`` (KLC-071), ``module_edges.json`` v2 and
``test_map.json`` (KLC-070), plus ``inventory.json`` — and answers the planning
index's core question: which minimal, checkable, explainable slice this feature
needs (modules to open first, files to read first, files likely to edit, relevant
tests, conditional neighbours, and where to stop).

Two modes (planning_indexer.md §"Query-time"):
  - ``deterministic`` (default) — no model. Matches the query against the
    deterministic layers only. This is the intake-path retriever: byte-reproducible
    and safe to run on every ticket.
  - ``assisted`` (opt-in) — a discovery/triage cold-path fallback that MAY layer
    embeddings/LLM routing over the same layers. Offline it degrades to the
    deterministic layers and records the fallback in ``reasons`` — it never invents
    a route, and it is never on the hot intake path by default.

Authority (planning_indexer.md §"Фазовая интеграция и authority") — CRITICAL:
  the retriever gives a HINT, not truth. It writes ONLY ``retrieval_trace.json``
  (advisory) and proposes ``affected_modules_hint``. It NEVER writes
  ``meta.affected_modules`` (that is the discovery agent's job, frozen by ``ack``).
  Every file→module attribution routes through the KLC-066 resolver
  ``module_membership.file_to_module`` — no private longest-prefix matcher is
  reintroduced (that would recreate the #1 risk the plan names: a second, divergent
  module set).

Degrade-not-fail (planning_indexer.md §"CLI / API контракты"): when the planning
views are absent the trace is written with ``status:"unavailable"`` and the process
exits 0 (intake never breaks). A weak prime match yields ``confidence:"low"`` plus a
widened keyword search. ``confidence`` (enum high|medium|low) and ``reasons`` are
present in every trace. Exit codes: ``0`` ok (including a degraded run); ``2`` bad
argument (missing required ``--ticket`` / ``--query``, handled by argparse).

The trace schema matches what ``planning-eval.py`` (KLC-067) reads: it uses
``files_to_read_first`` as the candidate ranking, so ``recall@5/10`` /
``precision@10`` / ``mean_files_before_first_edit`` compute directly from a produced
trace with no schema change on the eval side.

Determinism: ``build_trace`` is a PURE function with no timestamp; all lists are
sorted by a stable key, so the output is byte-identical on re-run for identical
inputs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Resolve imports the same way the other skills do so ``module_membership`` (the
# KLC-066 resolver) imports cleanly whether run as a script or loaded by path.
_FILE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _FILE_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_FILE_DIR))
from core.shared.inventory import (  # noqa: E402
    InventorySchemaError, load as inv_load, symbols as inv_symbols,
    symbol_range as inv_symbol_range)
import module_membership as _mm  # noqa: E402  (KLC-066: the one resolver)
import index_coverage  # noqa: E402
import math  # noqa: E402
import file_scanner  # noqa: E402  (KLC-123: the SAME extension-to-language map structural.json uses)

# Role priority for ranking eligible files (planning_indexer.md §"Retrieval
# workflow" step 4/5: entry points and public surfaces first, then domain logic).
_ROLE_PRIORITY = {
    "entrypoint": 0, "public_surface": 1, "domain_logic": 2, "types": 3,
    "adapter": 4, "persistence": 4, "integration": 4, "ui": 4,
}
# Tokens too generic to carry routing signal (mirrors file_roles._STOP_KEYWORDS).
_STOP_TOKENS = {
    "the", "and", "for", "add", "new", "rule", "with", "into", "from", "this",
    "that", "get", "set", "use", "via", "not", "but", "are", "was", "has",
    "incoming", "feature", "support", "make", "change", "update", "def", "class",
}
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_MODES = ("deterministic", "assisted")

# KLC-108: a module whose file-roles records are at least this fraction
# `is_test` never reaches `primary_modules` (AC-11, D-009).
_TEST_MODULE_RATIO = 0.8
# KLC-108 D-010: at most this many of a file's (uncapped) `symbols` fold into
# its strong signal — a large file's genuine identity should not drown in
# volume once IDF weighting already carries most of the down-weighting.
_SYMBOL_SIGNAL_CAP = 25
# KLC-137 AC-6: at most this many line_ranges entries per read-slice file,
# next to _SYMBOL_SIGNAL_CAP (D-104).
_LINE_RANGES_PER_FILE = 3
# KLC-108 AC-12/D-006, retuned by [!DECISION D-108-7] (step-8, real-corpus
# measurement): `confidence: high` requires the top module's normalised
# score to exceed the runner-up's by at least this ratio. Design's original
# `2.0` was derived from the spec's SIMULATED separations
# (1.79/2.23/2.47) — assumption A-102 explicitly licensed retuning it
# against step-8's real measurement "in the open, against AC-16 rather
# than against an impression". That measurement (110 archived klc tickets,
# each ticket's own recorded query replayed against the shipped retriever)
# found `2.0` insufficient: 27 of 110 tickets reported `confidence: high`
# together with `precision_at_5 == 0` (AC-16 requires 0) — including
# KLC-101 itself (separation 2.04x), the exact probe Q-005 says must
# demote. The highest separation among all 27 violators was 3.97x; `4.0`
# is the smallest round value strictly above it, and applying it to the
# same corpus drops violators to 0 of 110 while leaving every ranking
# number (precision_at_5, recall_at_10) UNCHANGED — the ratio only gates
# the confidence LABEL, never the ranking itself. See build-log.md step-8
# for the full before/after table.
_HIGH_SEPARATION_RATIO = 4.0

# Known role vocabulary (planning_indexer.md §3 file_roles roles). The generic
# ≥3-char length gate below would drop the only SHORT role token ('ui'), so a
# role-only `ui` query would never match. Whitelisting the actual role vocabulary
# lets short role names participate in matching while still dropping generic 2-char
# noise (`id`, `os`, `db`, …). All others are already ≥3 chars, so the set is
# effectively about 'ui' but is listed in full for clarity / future roles.
_KNOWN_ROLE_TOKENS = {
    "ui", "adapter", "config", "domain", "logic", "entrypoint", "public",
    "surface", "persistence", "fixture", "generated", "migration", "script",
    "integration", "types", "shared", "utility",
}


def _keep_token(p: str) -> bool:
    """True if a lowercase token should be kept: ≥3 chars OR a known (short) role
    token, and never a stop-word."""
    return (len(p) >= 3 or p in _KNOWN_ROLE_TOKENS) and p not in _STOP_TOKENS


# --------------------------------------------------------------------------- #
# tokenisation
# --------------------------------------------------------------------------- #
def tokenize(text: str) -> set[str]:
    """Deterministic lowercase token set from *text*, splitting snake_case and
    camelCase, dropping stop-words and tokens shorter than 3 chars (except known
    short role tokens like 'ui')."""
    out: set[str] = set()
    for word in _TOKEN_RE.findall(text or ""):
        for part in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", word):
            p = part.lower()
            if _keep_token(p):
                out.add(p)
    return out


def _path_tokens(path: str) -> set[str]:
    toks: set[str] = set()
    for seg in re.split(r"[/._-]", path):
        for part in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", seg):
            p = part.lower()
            if _keep_token(p):
                toks.add(p)
    return toks


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def load_token_idf(path: Path) -> dict:
    """Tolerant reader (D-005): an index built before this ticket, or one
    simply missing the artifact, must still score — every token then falls
    back to a uniform weight via `_weight`'s own default. Never raises."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _weight(token: str, idf: dict | None) -> float:
    """A token's scoring weight: its recorded IDF, or the table's own
    `default_idf` for a token absent from it, or a bare 1.0 when no table was
    loaded at all (AC-9's 'no literal stop-word list' — down-weighting comes
    only from this lookup)."""
    table = (idf or {}).get("tokens") or {}
    default = (idf or {}).get("default_idf", 1.0)
    return table.get(token, default)


def _capped_symbol_names(rec: dict, idf: dict | None = None) -> list[str]:
    """KLC-137 D-103: the at most `_SYMBOL_SIGNAL_CAP` names `_file_signal` folds
    into the strong signal, rarest (highest IDF weight) first. Moved out of
    `_file_signal` unchanged so `_line_ranges` uses the SAME "names folded into
    the strong signal" definition — there is exactly one such set, matching
    `strong_hits`'s own single-definition discipline."""
    names = rec.get("symbols") or []
    if len(names) > _SYMBOL_SIGNAL_CAP:
        names = sorted(
            names,
            key=lambda n: (-max((_weight(t, idf) for t in tokenize(n)), default=0.0), n),
        )[:_SYMBOL_SIGNAL_CAP]
    return list(names)


def _file_signal(path: str, rec: dict,
                 idf: dict | None = None) -> tuple[set[str], set[str], set[str]]:
    """Return (strong, role, weak) token sets for a file. Strong = keyword/symbol
    hits (semantic); role = the file's file_roles roles (coarse but real — a
    role-only query like 'adapter'/'persistence' must still match); weak = path
    tokens (positional). D-010: at most `_SYMBOL_SIGNAL_CAP` of the file's
    (possibly much larger) `symbols` list fold into the strong signal, rarest
    first by IDF weight — a large file's genuine identity should not drown in
    volume."""
    strong: set[str] = set()
    for kw in rec.get("keywords") or []:
        strong |= tokenize(kw)
    for sym in _capped_symbol_names(rec, idf):
        strong |= tokenize(sym)
    role: set[str] = set()
    for r in rec.get("roles") or []:
        role |= tokenize(r)
    weak = _path_tokens(path)
    return strong, role, weak


def _symbols_by_file_name(inventory) -> dict[tuple[str, str], list[dict]]:
    """KLC-137: `(file, name) -> [symbol dicts]` over the real inventory, or
    `{}` for an absent/degraded/wrong-shaped one — AC-7's "no line_ranges
    entry for an unusable inventory" degrades exactly like every other
    optional inventory read in this module."""
    try:
        syms = inv_symbols(inventory or {}, source="inventory")
    except InventorySchemaError:
        return {}
    index: dict[tuple[str, str], list[dict]] = {}
    for s in syms:
        # KLC-137 step-7 review-fix (AC-7): a stray non-dict/malformed element
        # must degrade like every other optional-input read in this module
        # (matching planning_validate.py's own `isinstance(s, dict)` guard),
        # never raise. `file`/`name` must also be real strings — either one
        # of another type would otherwise reach the hashed (file, name) key.
        if not isinstance(s, dict):
            continue
        file, name = s.get("file"), s.get("name")
        if not isinstance(file, str) or not isinstance(name, str):
            continue
        index.setdefault((file, name), []).append(s)
    return index


def _line_ranges(qtokens: set[str], paths, roles: dict, inventory,
                 idf: dict | None = None) -> dict[str, list[dict]]:
    """KLC-137 AC-5/AC-6: for each *path* in the two candidate lists, the at
    most `_LINE_RANGES_PER_FILE` `{"symbol", "kind", "start", "end"}` entries
    whose symbol NAME is one of `_capped_symbol_names` (the exact names
    `_file_signal` folds into the strong signal — a token reaching the
    strong set only through a `file_roles` keyword never creates an entry)
    AND intersects *qtokens*, deduplicated by `(symbol, kind, start, end)`
    and ordered by the IDF weight of the symbol's best matching token
    descending, then `start` ascending, then symbol name (D-104). A symbol
    whose `symbol_range()` is `None` (a regex-sourced or malformed entry) is
    silently excluded, never fabricated."""
    index = _symbols_by_file_name(inventory)
    out: dict[str, list[dict]] = {}
    for path in sorted(paths):
        best: dict[tuple, float] = {}
        for name in _capped_symbol_names(roles.get(path) or {}, idf):
            hit = tokenize(name) & qtokens
            if not hit:
                continue
            w = round(max(_weight(t, idf) for t in hit), 6)
            for sym in index.get((path, name), ()):
                rng = inv_symbol_range(sym)
                if rng is None:
                    continue
                key = (name, sym.get("kind") or "", rng[0], rng[1])
                best[key] = max(best.get(key, w), w)
        if best:
            keep = sorted(best, key=lambda k: (-best[k], k[2], k[0], k[1], k[3]))
            out[path] = [{"symbol": k[0], "kind": k[1], "start": k[2], "end": k[3]}
                         for k in keep[:_LINE_RANGES_PER_FILE]]
    return out


def strong_hits(qtokens: set[str], path: str, rec: dict,
               idf: dict | None = None) -> list[str]:
    """The keyword/symbol (strong) token intersection for one file — factored
    out of `score_file` so "strong hit" has exactly one definition, reused by
    AC-12's confidence rule (KLC-108 step-6, D-006)."""
    strong, _role, _weak = _file_signal(path, rec, idf)
    return sorted(qtokens & strong)


def score_file(qtokens: set[str], path: str, rec: dict,
              idf: dict | None = None) -> tuple[float, list[str]]:
    """Deterministic file score + human reasons. Strong (keyword/symbol) matches
    weigh 2x; role and path matches weigh 1x — a semantic hit beats a coarser
    role/positional one. Each matched token additionally weighs by its IDF
    (AC-9): a token present in more files contributes strictly less than one
    present in fewer. A token is counted once, at its strongest signal."""
    strong, role, weak = _file_signal(path, rec, idf)
    s_hits = sorted(qtokens & strong)
    r_hits = sorted((qtokens & role) - set(s_hits))
    w_hits = sorted((qtokens & weak) - set(s_hits) - set(r_hits))
    score = (2 * sum(_weight(t, idf) for t in s_hits)
            + sum(_weight(t, idf) for t in r_hits)
            + sum(_weight(t, idf) for t in w_hits))
    reasons: list[str] = []
    if s_hits:
        reasons.append(f"keyword/symbol match: {', '.join(s_hits)}")
    if r_hits:
        reasons.append(f"role match: {', '.join(r_hits)}")
    if w_hits:
        reasons.append(f"path match: {', '.join(w_hits)}")
    return score, reasons


def _module_signal(qtokens: set[str], m: dict,
                   idf: dict | None = None) -> tuple[float, list[str]]:
    """Score a module's own signal: keywords + summary + name/path tokens,
    each weighted by IDF (AC-9)."""
    kw: set[str] = set()
    for k in m.get("keywords") or []:
        kw |= tokenize(k)
    summ = tokenize(m.get("summary") or "")
    name_toks = _path_tokens(m.get("name") or "") | _path_tokens(m.get("path") or "")
    reasons: list[str] = []
    kw_hits = sorted(qtokens & (kw | summ))
    name_hits = sorted((qtokens & name_toks) - set(kw_hits))
    score = (2 * sum(_weight(t, idf) for t in kw_hits)
            + sum(_weight(t, idf) for t in name_hits))
    if kw_hits:
        reasons.append(f"module keyword/summary match: {', '.join(kw_hits)}")
    if name_hits:
        reasons.append(f"module name/path match: {', '.join(name_hits)}")
    return score, reasons


def module_score(own: float, best: float, aggregate: float, n_matched: int) -> float:
    """THE size-normalising module-score formula (AC-10):

        own_signal + best_file + aggregate / sqrt(n_matched)

    ``n_matched`` counts the module's files that scored above zero (not the
    module's total file count), so one genuine hit inside a 122-file module
    is not punished for the module's size, while the "many weak hits" bag
    effect the spec measured (`tests/integration`, 122 files) still is.

    [!DECISION D-108-4] owner=impl-agent refs=step-5, impl-plan-review F-2:
    design/options.md D-003 specified natural-log damping
    (``aggregate / log(1 + n_matched)``). Measured directly against the
    repository's own real worst case (122 files, each scoring 1, vs. one
    genuinely strong file scoring 10): log-damping gives the 122-file bag
    26.35 against the strong file's 24.43 — the bag WINS, which is exactly
    what AC-10 forbids and exactly the gap impl-plan-review finding F-2
    (low) flagged as under-tested. `sqrt` damping grows the divisor faster
    for large ``n`` (`sqrt(122) = 11.05` vs `log(123) = 4.81`), giving the
    same 122-file bag 12.05 against the strong file's 20 — comfortably
    ranked below — while leaving the 50:1 fixture's margin intact (8.07 vs
    20). `n_matched <= 0` short-circuits to ``own`` alone; `n_matched == 1`
    needs no special case (``sqrt(1) == 1``, so the divisor is never zero
    for any ``n_matched >= 1``)."""
    if n_matched <= 0:
        return own
    return own + best + aggregate / math.sqrt(n_matched)


def _test_heavy_modules(roles: dict) -> set[str]:
    """Modules whose file-roles records are >= `_TEST_MODULE_RATIO` tests
    (AC-11). A record with no `is_test` key counts toward the test side —
    D-009's fail-closed direction: a malformed record can keep a module OUT
    of `primary_modules`, never sneak one IN."""
    tally: dict[str, list[int]] = {}
    for rec in (roles or {}).values():
        name = (rec or {}).get("module_name")
        if not name:
            continue
        slot = tally.setdefault(name, [0, 0])
        slot[1] += 1
        if (rec or {}).get("is_test", True):
            slot[0] += 1
    return {n for n, (t, total) in tally.items()
           if total and t / total >= _TEST_MODULE_RATIO}


def _confidence_from_signal(top: float, runner_up: float,
                            strong_edit_hit: bool) -> tuple[str, str]:
    """AC-12: `confidence: high` requires BOTH the top module's score to
    exceed the runner-up's by at least `_HIGH_SEPARATION_RATIO` AND at
    least one `files_likely_to_edit` entry to carry a strong (keyword/
    symbol) hit. Returns (confidence, decided_by) — `decided_by` is the
    string `reasons[]` carries, naming which of the two conditions settled
    the outcome (D-006). When there is no runner-up, or the runner-up
    scores zero, the separation condition counts as met.

    D-108-8 (review round 1, HIGH #1): `top <= 0` is floored to `low`
    BEFORE that no-runner-up shortcut runs. Without this floor, a query
    that matches only a shared (cross-module) file never scores any
    module (the shared file's own score populates `shared_members`, not
    `mod_score`), so `top == runner_up == 0`; `separated` was trivially
    True at `runner_up <= 0` with no check that a real top module even
    exists, so a strong edit-slice hit alone (reached via the shared
    file's member-module focus path) reported `high` with
    `primary_modules == []` — the pre-ticket retriever returned `low` for
    the identical input."""
    if top <= 0:
        return "low", ("confidence held below high: no module scored "
                       "above zero")
    separated = runner_up <= 0 or (top / runner_up) >= _HIGH_SEPARATION_RATIO
    if separated and strong_edit_hit:
        ratio_text = f"{(top / runner_up):.2f}x" if runner_up > 0 else "no runner-up"
        return "high", (
            f"top module separated from runner-up by {ratio_text} "
            f"(>= {_HIGH_SEPARATION_RATIO}) and the edit slice carries a "
            f"keyword/symbol hit")
    if not separated:
        ratio = top / runner_up if runner_up > 0 else 0.0
        return ("medium" if top > 0 else "low"), (
            f"confidence held below high: separation {ratio:.2f}x is under "
            f"the {_HIGH_SEPARATION_RATIO} ratio")
    return ("medium" if top > 0 else "low"), (
        "confidence held below high: no files_likely_to_edit entry carries "
        "a keyword/symbol (strong) hit")


def _module_confidence(score: float, eligible_here: list[str]) -> str:
    """Per-module confidence (each `primary_modules[]` entry) — the same
    threshold this ticket found in place, factored into one named function
    (D-007) so KLC-106's `_cap_confidence` wraps it without either ticket
    rewriting the other."""
    if score >= 4 and eligible_here:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def _candidate_languages(paths) -> set[str]:
    """The languages of the trace's PRESENTED slices (KLC-123 AC-6, narrowed
    per review round-1 F-1 / operator ruling: `files_likely_to_edit` ∪
    `files_to_read_first`, not every matched (score > 0) file), via
    `file_scanner.EXT_LANG` — the SAME map `structural.json`'s own language
    classification uses, so no second, divergent mapping exists. `paths` is
    any iterable of path strings. An extensionless or unrecognised-extension
    path contributes nothing."""
    langs = set()
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if "." not in name:
            continue
        lang = file_scanner.EXT_LANG.get(name.rsplit(".", 1)[1].lower())
        if lang:
            langs.add(lang)
    return langs


def _role_rank(rec: dict) -> int:
    """Lowest (best) role-priority index among a file's roles."""
    ranks = [_ROLE_PRIORITY[r] for r in (rec.get("roles") or []) if r in _ROLE_PRIORITY]
    return min(ranks) if ranks else 99


# --------------------------------------------------------------------------- #
# trace assembly (pure)
# --------------------------------------------------------------------------- #
def _empty_trace(query: str, mode: str, status: str, confidence: str,
                 reasons: list[str], degraded_inputs: list[str] | None = None) -> dict:
    """A full-schema trace with empty slices — used for the degrade path so every
    schema key is always present (planning_indexer.md 'Retrieval result')."""
    return {
        "status": status,
        "mode": mode,
        "query": query,
        "primary_modules": [],
        "files_to_read_first": [],
        "files_likely_to_edit": [],
        "line_ranges": {},
        "tests_to_read_or_run": [],
        "conditional_neighbors": [],
        "affected_modules_hint": [],
        "unknown_or_ambiguous_modules": [],
        "stop_rules": ["Do not expand context until planning views are built."],
        "confidence": confidence,
        "reasons": reasons,
        "degraded_inputs": degraded_inputs or [],
        "coverage_advisories": [],
    }


def _cap_confidence(confidence: str, degraded_inputs: list[str]) -> str:
    """AC-10. Called at EVERY site in build_trace that produces a confidence
    value — the top-level score and each primary_modules[] entry — so no
    scoring branch can route around the cap and no trace can contradict
    itself by saying 'low' overall while one of its own primary modules says
    'high' (KLC-106 F-4, D-204)."""
    return "low" if degraded_inputs else confidence


def _neighbor_condition(edge: dict) -> str:
    """Deterministic condition string for a conditional neighbour."""
    types = ", ".join(edge.get("edge_types") or []) or "dependency"
    conf = edge.get("confidence") or "low"
    if edge.get("expand_by_default"):
        return (f"Open if the change affects the {types} contract "
                f"(edge confidence {conf}).")
    return (f"Open only if the {types} boundary is touched "
            f"(edge confidence {conf}).")


def build_trace(query: str, mode: str, modules: dict, file_roles: dict,
                module_edges: dict, test_map: dict,
                inventory: dict | None = None,
                token_idf: dict | None = None) -> dict:
    """Pure, byte-stable retrieval trace (see module docstring). ``inventory`` is
    accepted for parity with the CLI/plan but the deterministic ranking is driven
    by file_roles (which already derives keywords/symbols from inventory).
    KLC-137: ``inventory`` also feeds ``line_ranges`` — the per-symbol
    ``(start, end)`` line ranges attached to files in ``files_to_read_first``/
    ``files_likely_to_edit`` (AC-5/AC-6); an inventory without ``line_end``
    (built before this ticket) yields ``line_ranges: {}`` (AC-7).

    ``token_idf`` (KLC-108, optional) is the ``.klc/index/token_idf.json``
    table: every matched token is weighted by its recorded inverse document
    frequency (AC-9) rather than by a flat count. A missing/absent table
    degrades to a uniform weight (D-005's tolerant fallback) — an index built
    before this ticket still scores.

    The module score is ONE stated, size-normalising formula (AC-10; see
    `module_score`'s own docstring for D-108-4, which revises D-003's
    log-based divisor to sqrt after measuring it against the repository's
    real worst-case module size):

        own_signal + best_file + aggregate / sqrt(n_matched)

    ``n_matched`` is the count of the module's files that scored above zero.
    A module whose file-roles records are >= 80% ``is_test`` never reaches
    ``primary_modules`` (AC-11) — its tests still reach
    ``tests_to_read_or_run`` via the module-to-tests lookup."""
    reasons: list[str] = []
    effective_mode = mode

    # assisted opt-in: offline it degrades to the deterministic layers (never
    # breaks intake, never invents a route). No model client is imported.
    if mode == "assisted":
        reasons.append("assisted mode requested; no model available offline — "
                       "degraded to the deterministic layers")

    modules_list = modules.get("modules") or []
    roles = (file_roles or {}).get("files") or {}

    # Degrade-not-fail: BOTH modules.json and file_roles.json are required planning
    # views, so the retriever degrades to status:"unavailable" (exit 0, full schema,
    # honest reason) when either is absent — a status:"ok" trace with empty
    # attribution/reads would mislead a consumer (intake never breaks).
    #   - file_roles.json is the sole source of the read slice
    #     (files_to_read_first / files_likely_to_edit) AND the eval seam's
    #     candidate list.
    #   - modules.json is the sole source of module attribution; without it every
    #     file resolves to 'orphan', so primary_modules / affected_modules_hint /
    #     conditional_neighbors would all be empty.
    if not roles or not modules_list:
        if not roles and not modules_list:
            reasons.append("planning views unavailable (no modules.json / "
                           "file_roles.json) — retrieval degraded to status:unavailable")
        elif not modules_list:
            reasons.append("modules.json absent — no module attribution; "
                           "retrieval degraded to status:unavailable")
        else:
            reasons.append("file_roles.json unavailable — no read candidates; "
                           "retrieval degraded to status:unavailable")
        return _empty_trace(query, effective_mode, "unavailable", "low", reasons)

    # --- honest evidence accounting (AC-9) --------------------------------
    # `edges`/`roles_vacuous` are needed both here and further down (AC-11's
    # name-match-only mode), so they stay computed at this point.
    edges = (module_edges or {}).get("edges") or []
    roles_vacuous = bool(roles) and not any(
        (rec or {}).get("roles") for rec in roles.values())

    qtokens = tokenize(query)

    # --- score every known file ------------------------------------------------
    scored: dict[str, dict] = {}   # path -> {score, reasons, rec, membership}
    for path, rec in roles.items():
        score, freasons = score_file(qtokens, path, rec, token_idf)
        membership = _mm.file_to_module(path, modules)
        scored[path] = {"score": score, "reasons": freasons, "rec": rec,
                        "membership": membership}

    matched = {p: d for p, d in scored.items() if d["score"] > 0}

    widened = False
    if not matched and qtokens:
        # Weak prime match: widen the search to eligible domain files so the slice
        # is never empty, and flag the low confidence honestly.
        widened = True
        reasons.append("weak prime match — widened keyword search over paths/roles")

    # --- aggregate to modules (AC-10: own_signal + best_file + normalised) ----
    own_signal: dict[str, float] = {}
    mod_reasons: dict[str, list[str]] = {}
    for m in modules_list:
        name = m.get("name")
        if not name:
            continue
        s, r = _module_signal(qtokens, m, token_idf)
        if s:
            own_signal[name] = own_signal.get(name, 0.0) + s
            mod_reasons.setdefault(name, []).extend(r)
    # A matched SHARED file (primary_module=None, member_of set) must not be
    # stranded: the KLC-066 resolver models it via member_of precisely so its
    # consumer modules surface. Track them to seed the hint + conditional neighbours
    # (the shared file itself stays out of files_to_read_first — it is not eligible).
    shared_members: dict[str, list[str]] = {}
    file_aggregate: dict[str, float] = {}
    file_best: dict[str, float] = {}
    file_n_matched: dict[str, int] = {}
    for path, d in matched.items():
        mem = d["membership"]
        pm = mem["primary_module"]
        if pm:
            file_aggregate[pm] = file_aggregate.get(pm, 0.0) + d["score"]
            file_best[pm] = max(file_best.get(pm, 0.0), d["score"])
            file_n_matched[pm] = file_n_matched.get(pm, 0) + 1
            mod_reasons.setdefault(pm, [])
        elif mem["member_of"]:
            for mod in mem["member_of"]:
                shared_members.setdefault(mod, []).append(path)

    mod_score: dict[str, float] = {
        name: module_score(own_signal.get(name, 0.0), file_best.get(name, 0.0),
                           file_aggregate.get(name, 0.0), file_n_matched.get(name, 0))
        for name in set(own_signal) | set(file_aggregate)
    }

    # AC-11: a module whose file-roles records are >= 80% is_test never
    # reaches primary_modules — its tests still reach tests_to_read_or_run
    # via module_to_tests below (the bar excludes it only from RANKING).
    test_heavy_modules = _test_heavy_modules(roles)

    # Primary modules: top by score (rounded key so a last-ulp libm
    # difference cannot reorder a near-tie, D-003), tie-break by name, max 3.
    ranked_mods = sorted(
        ((n, s) for n, s in mod_score.items() if n not in test_heavy_modules),
        key=lambda kv: (-round(kv[1], 6), kv[0]),
    )[:3]

    # Module SELECTION (which modules rank, and which of their files are
    # eligible_as_primary) is independent of trace_degraded_inputs and is
    # resolved here, before the cap. Only the CONFIDENCE VALUE attached to
    # each selected module (the primary_modules loop below) is produced
    # strictly after trace_degraded_inputs is known — KLC-106 D-204's
    # ordering constraint is unchanged, it now applies to that later loop
    # instead of this selection step. KLC-123 needs the split because
    # candidate_languages (AC-6) is scoped to the trace's PRESENTED slices
    # (files_likely_to_edit ∪ files_to_read_first — review round-1 F-1 /
    # operator ruling, see D-123-4 in build-log.md), and those slices are
    # themselves derived from primary_names/eligible_here, so module
    # selection must run before the cap is computed.
    primary_names: list[str] = []
    eligible_here_by_module: dict[str, list[str]] = {}
    for name, sc in ranked_mods:
        if sc <= 0:
            continue
        eligible_here_by_module[name] = [
            p for p, d in matched.items()
            if d["membership"]["primary_module"] == name
            and d["rec"].get("eligible_as_primary")
        ]
        primary_names.append(name)

    # --- files_to_read_first ---------------------------------------------------
    # Only eligible files become primary reads (shared/generated/test/config never).
    # A selected module contributes ALL its eligible files (planning_indexer.md
    # "Открыть … primary files; public surfaces"), not just the query-matched ones,
    # so the slice includes the module's entry/public/domain files. When nothing
    # matched (widened / empty query) fall back to every eligible file.
    def _eligible(d: dict) -> bool:
        # Trust file_roles' eligible_as_primary flag, but defensively re-exclude a
        # test/generated/config file even if a malformed record flags it eligible —
        # such a file must never enter the read slice (belt-and-suspenders).
        rec = d["rec"]
        if not rec.get("eligible_as_primary"):
            return False
        if rec.get("is_test") or rec.get("is_generated") or rec.get("is_config"):
            return False
        return True

    # Focus the read slice on the selected modules; when only a shared file matched
    # (no primary), focus on its member modules rather than the whole eligible set.
    if primary_names:
        focus: set[str] | None = set(primary_names)
    elif shared_members:
        focus = set(shared_members)
    else:
        focus = None
    if focus is not None:
        read_pool = {p: d for p, d in scored.items()
                     if d["membership"]["primary_module"] in focus}
    else:
        read_pool = scored
    read_candidates = [(p, d) for p, d in read_pool.items() if _eligible(d)]
    # Rank: score desc, role priority asc, path asc (all deterministic).
    read_candidates.sort(key=lambda pd: (-pd[1]["score"], _role_rank(pd[1]["rec"]), pd[0]))
    files_to_read_first = [p for p, _ in read_candidates][:10]

    # files_likely_to_edit: the strongest eligible domain/public/entry files.
    edit_candidates = [
        (p, d) for p, d in read_candidates
        if d["score"] > 0
        and (set(d["rec"].get("roles") or [])
             & {"domain_logic", "public_surface", "entrypoint"})
    ]
    files_likely_to_edit = [p for p, _ in edit_candidates][:5]

    # KLC-137 AC-5/AC-6: computed now that both lists are final.
    line_ranges = _line_ranges(
        qtokens, set(files_to_read_first) | set(files_likely_to_edit),
        roles, inventory, token_idf)

    # The trace_degraded_inputs assembly (KLC-106 D-204's ordering
    # constraint: strictly BEFORE the loop that produces
    # primary_modules[].confidence, since both are capped by the same value)
    # is placed HERE — now that the trace's PRESENTED slices are known — so
    # the inventory candidate can be scoped to those slices (KLC-123 AC-6,
    # narrowed per review round-1 F-1 / operator ruling: confidence is a
    # claim about the slice the reader is told to edit, so a file that
    # merely scored > 0 for an incidental weak path-segment token — e.g. a
    # fixture/test file that never surfaces in either read slice — must not
    # pull its language into scope; see D-123-4 in build-log.md). A degraded
    # language outside the relevant set surfaces as an additive advisory
    # (AC-7) rather than capping.
    candidate_languages = _candidate_languages(
        set(files_to_read_first) | set(files_likely_to_edit))
    inv_degraded, coverage_advisories, inv_scoped = (
        index_coverage.scoped_inventory_degradation(inventory, candidate_languages))
    if not inv_scoped:
        inv_degraded = index_coverage.artifact_degraded(inventory)

    trace_degraded_inputs = index_coverage.degraded_inputs([
        ("module_edges.json", module_edges, not edges),
        ("file_roles.json", file_roles, roles_vacuous),
        ("test_map.json", test_map, False),
        ("modules.json", modules, False),
    ])
    if inv_degraded:
        trace_degraded_inputs = sorted(set(trace_degraded_inputs) | {"inventory.json"})

    # primary_modules confidence — produced strictly AFTER trace_degraded_inputs
    # (KLC-106 D-204), reusing the module selection and eligible-file sets
    # already resolved above.
    primary_modules: list[dict] = []
    for name in primary_names:
        sc = mod_score[name]
        eligible_here = eligible_here_by_module[name]
        conf = _module_confidence(sc, eligible_here)
        conf = _cap_confidence(conf, trace_degraded_inputs)
        pr = sorted(set(mod_reasons.get(name, [])))
        if not pr:
            pr = [f"aggregate file-match score {sc} in module {name}"]
        primary_modules.append({"module_name": name, "confidence": conf, "reasons": pr})

    # --- tests -----------------------------------------------------------------
    p2t = (test_map or {}).get("production_to_tests") or {}
    m2t = (test_map or {}).get("module_to_tests") or {}
    tests: set[str] = set()
    for p in files_to_read_first:
        for row in (p2t.get(p) or {}).get("tests") or []:
            if row.get("test_file"):
                tests.add(row["test_file"])
    # Module-level tests for every surfaced module: primary modules PLUS the member
    # modules of a matched shared file (FIX-B), PLUS any matched test-heavy module
    # barred from primary_modules by AC-11/D-009 — its tests still reach this list,
    # they just arrive as tests rather than as a focus module.
    barred_but_matched = {n for n in mod_score if n in test_heavy_modules}
    for name in set(primary_names) | set(shared_members) | barred_but_matched:
        for tf in m2t.get(name) or []:
            tests.add(tf)
    tests_to_read_or_run = sorted(tests)

    # --- conditional neighbours (one hop via module_edges) ---------------------
    neighbors: dict[str, dict] = {}
    for e in edges:
        frm, to = e.get("from"), e.get("to")
        if frm in primary_names and to and to not in primary_names:
            neighbors.setdefault(to, {"module_name": to,
                                      "condition": _neighbor_condition(e)})
        elif to in primary_names and frm and frm not in primary_names:
            neighbors.setdefault(frm, {"module_name": frm,
                                       "condition": _neighbor_condition(e)})
    # Shared-file member modules that are not already primary surface as conditional
    # neighbours (FIX-2): the change may affect them through the shared file.
    for mod, paths in shared_members.items():
        if mod in primary_names:
            continue
        files = ", ".join(sorted(set(paths)))
        neighbors.setdefault(mod, {
            "module_name": mod,
            "condition": (f"Open if the change touches shared file(s): {files} "
                          f"(this module is a member_of them)."),
        })
    conditional_neighbors = [neighbors[k] for k in sorted(neighbors)]

    # --- affected_modules_hint (advisory — NEVER meta.affected_modules) --------
    # Primary modules plus the member modules of any matched shared file (so a
    # shared-file match is never dropped from the scope hint).
    affected_modules_hint = sorted(set(primary_names) | set(shared_members))

    # --- unknown_or_ambiguous_modules -----------------------------------------
    # Matched files the resolver could not place in a module (orphans) are ambiguous
    # and discovery must resolve them before writing the authoritative scope.
    unknown = sorted({
        p for p, d in matched.items()
        if d["membership"]["resolution_source"] == "orphan"
    })

    # --- overall confidence + reasons -----------------------------------------
    # AC-12: high requires BOTH separation (top vs. runner-up) AND a strong
    # edit-slice hit, via the ONE helper `_confidence_from_signal` (D-006/
    # D-007) — its `decided_by` string is what names the deciding condition.
    top_score = ranked_mods[0][1] if ranked_mods else 0
    runner_up_score = ranked_mods[1][1] if len(ranked_mods) > 1 else 0
    strong_edit_hit = any(
        strong_hits(qtokens, p, scored[p]["rec"], token_idf)
        for p in files_likely_to_edit
    )
    if not matched:
        confidence = "low"
        decided_by = ""
        if not widened:
            reasons.append("no keyword/symbol match for the query")
    else:
        confidence, decided_by = _confidence_from_signal(
            top_score, runner_up_score, strong_edit_hit)

    confidence = _cap_confidence(confidence, trace_degraded_inputs)
    if decided_by:
        reasons.append(decided_by)
    if trace_degraded_inputs:
        reasons.append("degraded inputs — confidence capped at low: "
                       + ", ".join(trace_degraded_inputs))

    # AC-11: ranking rested on names and paths alone because no edge
    # contributed. The trigger is zero edges, not a low ratio: a partial
    # edge set still ranks.
    if not edges:
        effective_mode = "name-match-only"
        reasons.append("module_edges contributed no edges — module ranking "
                       "rests on name and path matches alone")

    if primary_names:
        reasons.append(f"primary modules by evidence: {', '.join(primary_names)}")
    if shared_members and not primary_names:
        reasons.append("matched a shared file — surfacing its member modules: "
                       f"{', '.join(sorted(shared_members))}")
    if not reasons:
        reasons.append("deterministic keyword/role match over planning views")

    # --- stop rules (deterministic) -------------------------------------------
    stop_rules = [
        "Do not expand beyond graph depth 1 unless the implementation plan requires it.",
        "When adding a file outside this slice, state the reason.",
    ]
    for n in conditional_neighbors:
        stop_rules.append(
            f"Do not open module '{n['module_name']}' unless: {n['condition']}")

    return {
        "status": "ok",
        "mode": effective_mode,
        "query": query,
        "primary_modules": primary_modules,
        "files_to_read_first": files_to_read_first,
        "files_likely_to_edit": files_likely_to_edit,
        "line_ranges": line_ranges,
        "tests_to_read_or_run": tests_to_read_or_run,
        "conditional_neighbors": conditional_neighbors,
        "affected_modules_hint": affected_modules_hint,
        "unknown_or_ambiguous_modules": unknown,
        "stop_rules": stop_rules,
        "confidence": confidence,
        "reasons": reasons,
        "degraded_inputs": trace_degraded_inputs,
        "coverage_advisories": coverage_advisories,
    }


# --------------------------------------------------------------------------- #
# I/O + CLI
# --------------------------------------------------------------------------- #
def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"modules": data}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_inventory(path: Path) -> dict:
    """D-2 / F-2 / AC-6: inventory specifically routes through the shared
    accessor instead of the generic `_load()`. `required=False` keeps the
    existing silent degrade on an absent or present-but-corrupt file; a
    present-but-WRONG-SHAPED file still raises `InventorySchemaError` (that
    check does not depend on `required`) — caught here rather than crashing,
    since `build_trace()` treats `inventory` as fully optional (its own
    docstring: accepted but currently ignored)."""
    try:
        data = inv_load(path, required=False)
    except InventorySchemaError as exc:
        sys.stderr.write(f"planning-retriever: warning: {exc}\n")
        return {}
    return data if isinstance(data, dict) else {}


def main(argv: list[str] | None = None) -> int:
    import os

    def _base() -> Path:
        root = os.environ.get("PROJECT_ROOT")
        return Path(root).resolve() if root else _PROJECT_ROOT.parent

    idx = _base() / ".klc" / "index"
    ap = argparse.ArgumentParser(description="query-time planning retriever (KLC-068)")
    ap.add_argument("--ticket", required=True, help="ticket key (e.g. KLC-068)")
    ap.add_argument("--query", required=True, help="short feature-description query")
    ap.add_argument("--mode", choices=_MODES, default="deterministic",
                    help="deterministic (default, no model) | assisted (opt-in)")
    ap.add_argument("--in-modules", type=Path, default=idx / "modules.json")
    ap.add_argument("--in-file-roles", type=Path, default=idx / "file_roles.json")
    ap.add_argument("--in-module-edges", type=Path, default=idx / "module_edges.json")
    ap.add_argument("--in-test-map", type=Path, default=idx / "test_map.json")
    ap.add_argument("--in-inventory", type=Path, default=idx / "inventory.json")
    ap.add_argument("--in-token-idf", type=Path, default=idx / "token_idf.json")
    ap.add_argument("--out", type=Path, default=None,
                    help="output trace path (default .klc/scratch/<KEY>/retrieval_trace.json)")
    args = ap.parse_args(argv)

    if args.out is None:
        # KLC-176: the trace is derived, so it lives under the card root
        # (`.klc/scratch/<KEY>/`), not in the tracked ticket directory.
        from core.shared.paths import transient_dir
        out = transient_dir(args.ticket) / "retrieval_trace.json"
    else:
        out = args.out

    modules = _load(args.in_modules)
    file_roles = _load(args.in_file_roles)
    module_edges = _load(args.in_module_edges)
    test_map = _load(args.in_test_map)
    inventory = _load_inventory(args.in_inventory)
    token_idf = load_token_idf(args.in_token_idf)

    trace = build_trace(args.query, args.mode, modules, file_roles,
                        module_edges, test_map, inventory, token_idf)

    # Authority: the retriever writes ONLY the trace. It never opens or writes
    # meta.json / meta.affected_modules (planning_indexer.md §Authority).
    payload = json.dumps(trace, indent=2, ensure_ascii=False) + "\n"
    if str(out) == "-":
        sys.stdout.write(payload)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        sys.stderr.write(
            f"planning-retriever: {trace['status']} "
            f"(confidence={trace['confidence']}) → {out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
