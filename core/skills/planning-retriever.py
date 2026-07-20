#!/usr/bin/env python3
"""planning-retriever.py — query-time planning retriever (KLC-068).

The **query-time capstone** of the planning index (planning_indexer.md
§"Query-time: retriever, а не статический router"). It turns a feature
description into a ranked, explainable project slice and materialises it per
ticket as ``.klc/tickets/<KEY>/retrieval_trace.json``.

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
import module_membership as _mm  # noqa: E402  (KLC-066: the one resolver)

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
def _file_signal(path: str, rec: dict) -> tuple[set[str], set[str], set[str]]:
    """Return (strong, role, weak) token sets for a file. Strong = keyword/symbol
    hits (semantic); role = the file's file_roles roles (coarse but real — a
    role-only query like 'adapter'/'persistence' must still match); weak = path
    tokens (positional)."""
    strong: set[str] = set()
    for kw in rec.get("keywords") or []:
        strong |= tokenize(kw)
    for sym in rec.get("symbols") or []:
        strong |= tokenize(sym)
    role: set[str] = set()
    for r in rec.get("roles") or []:
        role |= tokenize(r)
    weak = _path_tokens(path)
    return strong, role, weak


def score_file(qtokens: set[str], path: str, rec: dict) -> tuple[int, list[str]]:
    """Deterministic file score + human reasons. Strong (keyword/symbol) matches
    weigh 2; role and path matches weigh 1 — a semantic hit beats a coarser
    role/positional one. A token is counted once, at its strongest signal."""
    strong, role, weak = _file_signal(path, rec)
    s_hits = sorted(qtokens & strong)
    r_hits = sorted((qtokens & role) - set(s_hits))
    w_hits = sorted((qtokens & weak) - set(s_hits) - set(r_hits))
    score = 2 * len(s_hits) + len(r_hits) + len(w_hits)
    reasons: list[str] = []
    if s_hits:
        reasons.append(f"keyword/symbol match: {', '.join(s_hits)}")
    if r_hits:
        reasons.append(f"role match: {', '.join(r_hits)}")
    if w_hits:
        reasons.append(f"path match: {', '.join(w_hits)}")
    return score, reasons


def _module_signal(qtokens: set[str], m: dict) -> tuple[int, list[str]]:
    """Score a module's own signal: keywords + summary + name/path tokens."""
    kw: set[str] = set()
    for k in m.get("keywords") or []:
        kw |= tokenize(k)
    summ = tokenize(m.get("summary") or "")
    name_toks = _path_tokens(m.get("name") or "") | _path_tokens(m.get("path") or "")
    reasons: list[str] = []
    kw_hits = sorted(qtokens & (kw | summ))
    name_hits = sorted((qtokens & name_toks) - set(kw_hits))
    score = 2 * len(kw_hits) + len(name_hits)
    if kw_hits:
        reasons.append(f"module keyword/summary match: {', '.join(kw_hits)}")
    if name_hits:
        reasons.append(f"module name/path match: {', '.join(name_hits)}")
    return score, reasons


def _role_rank(rec: dict) -> int:
    """Lowest (best) role-priority index among a file's roles."""
    ranks = [_ROLE_PRIORITY[r] for r in (rec.get("roles") or []) if r in _ROLE_PRIORITY]
    return min(ranks) if ranks else 99


# --------------------------------------------------------------------------- #
# trace assembly (pure)
# --------------------------------------------------------------------------- #
def _empty_trace(query: str, mode: str, status: str, confidence: str,
                 reasons: list[str]) -> dict:
    """A full-schema trace with empty slices — used for the degrade path so every
    schema key is always present (planning_indexer.md 'Retrieval result')."""
    return {
        "status": status,
        "mode": mode,
        "query": query,
        "primary_modules": [],
        "files_to_read_first": [],
        "files_likely_to_edit": [],
        "tests_to_read_or_run": [],
        "conditional_neighbors": [],
        "affected_modules_hint": [],
        "unknown_or_ambiguous_modules": [],
        "stop_rules": ["Do not expand context until planning views are built."],
        "confidence": confidence,
        "reasons": reasons,
    }


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
                inventory: dict | None = None) -> dict:
    """Pure, byte-stable retrieval trace (see module docstring). ``inventory`` is
    accepted for parity with the CLI/plan but the deterministic ranking is driven
    by file_roles (which already derives keywords/symbols from inventory)."""
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

    qtokens = tokenize(query)

    # --- score every known file ------------------------------------------------
    scored: dict[str, dict] = {}   # path -> {score, reasons, rec, membership}
    for path, rec in roles.items():
        score, freasons = score_file(qtokens, path, rec)
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

    # --- aggregate to modules --------------------------------------------------
    mod_score: dict[str, int] = {}
    mod_reasons: dict[str, list[str]] = {}
    for m in modules_list:
        name = m.get("name")
        if not name:
            continue
        s, r = _module_signal(qtokens, m)
        if s:
            mod_score[name] = mod_score.get(name, 0) + s
            mod_reasons.setdefault(name, []).extend(r)
    # A matched SHARED file (primary_module=None, member_of set) must not be
    # stranded: the KLC-066 resolver models it via member_of precisely so its
    # consumer modules surface. Track them to seed the hint + conditional neighbours
    # (the shared file itself stays out of files_to_read_first — it is not eligible).
    shared_members: dict[str, list[str]] = {}
    for path, d in matched.items():
        mem = d["membership"]
        pm = mem["primary_module"]
        if pm:
            mod_score[pm] = mod_score.get(pm, 0) + d["score"]
            mod_reasons.setdefault(pm, [])
        elif mem["member_of"]:
            for mod in mem["member_of"]:
                shared_members.setdefault(mod, []).append(path)

    # Primary modules: top by score (deterministic tie-break by name), max 3.
    ranked_mods = sorted(mod_score.items(), key=lambda kv: (-kv[1], kv[0]))[:3]

    primary_modules: list[dict] = []
    primary_names: list[str] = []
    for name, sc in ranked_mods:
        if sc <= 0:
            continue
        eligible_here = [
            p for p, d in matched.items()
            if d["membership"]["primary_module"] == name
            and d["rec"].get("eligible_as_primary")
        ]
        conf = "high" if (sc >= 4 and eligible_here) else ("medium" if sc >= 2 else "low")
        pr = sorted(set(mod_reasons.get(name, [])))
        if not pr:
            pr = [f"aggregate file-match score {sc} in module {name}"]
        primary_modules.append({"module_name": name, "confidence": conf, "reasons": pr})
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

    # --- tests -----------------------------------------------------------------
    p2t = (test_map or {}).get("production_to_tests") or {}
    m2t = (test_map or {}).get("module_to_tests") or {}
    tests: set[str] = set()
    for p in files_to_read_first:
        for row in (p2t.get(p) or {}).get("tests") or []:
            if row.get("test_file"):
                tests.add(row["test_file"])
    # Module-level tests for every surfaced module: primary modules PLUS the member
    # modules of a matched shared file (FIX-B) — otherwise a shared-only match
    # surfaces the member modules in the hint but omits their module-level tests.
    for name in set(primary_names) | set(shared_members):
        for tf in m2t.get(name) or []:
            tests.add(tf)
    tests_to_read_or_run = sorted(tests)

    # --- conditional neighbours (one hop via module_edges) ---------------------
    edges = (module_edges or {}).get("edges") or []
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
    top_score = ranked_mods[0][1] if ranked_mods else 0
    if not matched:
        confidence = "low"
        if not widened:
            reasons.append("no keyword/symbol match for the query")
    elif top_score >= 4 and files_likely_to_edit:
        confidence = "high"
    elif top_score >= 2:
        confidence = "medium"
    else:
        confidence = "low"

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
        "tests_to_read_or_run": tests_to_read_or_run,
        "conditional_neighbors": conditional_neighbors,
        "affected_modules_hint": affected_modules_hint,
        "unknown_or_ambiguous_modules": unknown,
        "stop_rules": stop_rules,
        "confidence": confidence,
        "reasons": reasons,
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
    ap.add_argument("--out", type=Path, default=None,
                    help="output trace path (default .klc/tickets/<KEY>/retrieval_trace.json)")
    args = ap.parse_args(argv)

    out = args.out or (_base() / ".klc" / "tickets" / args.ticket / "retrieval_trace.json")

    modules = _load(args.in_modules)
    file_roles = _load(args.in_file_roles)
    module_edges = _load(args.in_module_edges)
    test_map = _load(args.in_test_map)
    inventory = _load(args.in_inventory)

    trace = build_trace(args.query, args.mode, modules, file_roles,
                        module_edges, test_map, inventory)

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
