#!/usr/bin/env python3
"""deterministic_inventory.py — no-LLM symbol inventory (KLC-070 step-1).

Runs the ACTIVE PROFILE's ast-grep rule set (``core/rules/*`` merged with the
profile's own rule dirs and its ``sgconfig`` languageGlobs) over the repo and writes
``inventory.json`` with a FROZEN symbol schema. No agent, no LLM — it runs in the
deterministic scan-only path (``init.py --scan-only``). It degrades to a regex fallback
when ast-grep is unavailable (``source_of_truth="regex"``, recorded in ``errors[]``),
and never hard-fails on a missing optional tool — the only exit-2 case is a ``--root``
that is not a directory.

Profile-awareness matters: the active profile is resolved via ``profile-resolve.py``,
so the UE profile's ``profiles/ue/rules/cpp-unreal`` rules and its ``.h -> cpp``
languageGlobs are applied. Merging by hand (only ``core/rules``) would make the UE
public-API index worse than the LLM-agent path.

FROZEN inventory.json schema — stated ONCE, in ``core.shared.inventory``
(``CANONICAL_SCHEMA`` / ``SYMBOL_FIELDS``), not here (KLC-103 migration note: this
docstring used to carry its own copy of the shape; it now points at the single
statement so the schema cannot drift into two documents). KLC-071 and every reader
of ``inventory.json`` build on that one statement:

    {
      "root":            "<abs path>",
      "profile":         "<active profile name>",
      "source_of_truth": {"<lang>": "ast_grep" | "regex"},   # per language
      "symbols": [                                           # flat, byte-sorted list
        {"name": str, "kind": str, "file": str, "line": int,
         "signature": str, "visibility": "public" | "private",
         "source_of_truth": "ast_grep" | "regex",
         "lang": str, "rule": str}
      ],
      "errors": [str],
      "notes":  [str]
    }

``build_inventory()`` is a deterministic function of (root, ruleset, astgrep_path): it
returns NO timestamp, so ``symbols`` and the whole payload are byte-identical on re-run
(AC-11). ``main()`` adds ``generated_at`` only at the TOP level of the written file,
matching ``modules_build.py``.

CLI (planning_indexer.md §"CLI / API контракты"):
    deterministic_inventory.py --root . --profile <name> --out .klc/index/inventory.json
  exit 0 ok; exit 2 when --root is not a directory; ast-grep missing/failing degrades
  to regex with an errors[] note (never fails the pipeline).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_file_dir))
from core.shared.paths import klc_index_dir, framework_root, project_root  # noqa: E402
from core.shared import inventory as _inv  # noqa: E402  — KLC-103's canonical accessor
import tools as _tools  # noqa: E402
import file_universe  # noqa: E402
import index_coverage  # noqa: E402

# KLC-105: ast-grep is invoked with an explicit positional PATHS list (chunked under
# this budget) instead of scanning "." — a builder must not decide the universe by
# walking. Chars of positional paths per invocation; real ARG_MAX is ~2 MiB, this is
# a conservative budget that leaves headroom for the rest of argv + environment.
_ARG_BUDGET = 100_000

# ast-grep 0-based line/column ranges -> 1-based editor lines.
_SIG_MAX = 200

# Regex-fallback patterns (lower fidelity than ast-grep; used only when the binary
# is unavailable). Public = identifier not starting with "_".
_PY_DEF_RE = re.compile(r"^\s*(?:async\s+def|def)\s+([A-Za-z][A-Za-z0-9_]*)\s*\(")
_PY_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z][A-Za-z0-9_]*)\b")
_TS_EXPORT_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?(function|class|interface|type|enum|const)\s+"
    r"([A-Za-z_$][A-Za-z0-9_$]*)\b"
)
_HIDDEN_OR_NOISE = re.compile(r"(^|/)(\.[^/]+|node_modules|__pycache__)(/|$)")


# --- profile resolution -------------------------------------------------------

def _resolve_field(field: str) -> str:
    """Run ``profile-resolve.py --field <field>`` and return stdout (stripped).

    Returns "" on any failure — the caller degrades (this mirrors dep_graph.py's
    ``_resolve`` so the inventory never hard-fails on a profile hiccup).
    """
    script = framework_root() / "core" / "skills" / "profile-resolve.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), "--field", field],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def resolve_ruleset() -> dict:
    """Resolve the active profile's rule set into absolute paths + languageGlobs.

    Returns ``{"profile", "rule_dirs": [abs], "excludes_re": str,
    "language_globs": {lang: [glob]}}``. Rule dirs and the sgconfig are resolved
    relative to ``framework_root()`` (they ship with the framework, per the manifest
    comment "Paths are relative to the repo root").
    """
    fr = framework_root()
    profile = _resolve_field("name") or "generic"
    excludes_re = _resolve_field("excludes-regex")

    rule_dirs: list[str] = []
    for rel in _resolve_field("rules").splitlines():
        rel = rel.strip()
        if not rel:
            continue
        p = (fr / rel).resolve()
        if p.is_dir():
            rule_dirs.append(str(p))

    language_globs: dict[str, list[str]] = {}
    sgconfig_rel = _resolve_field("sgconfig")
    if sgconfig_rel:
        sg_path = (fr / sgconfig_rel).resolve()
        if sg_path.exists():
            try:
                import yaml  # local import: only the UE path needs it
                sg = yaml.safe_load(sg_path.read_text(encoding="utf-8")) or {}
                lg = sg.get("languageGlobs")
                if isinstance(lg, dict):
                    language_globs = lg
            except Exception:
                # A broken sgconfig must not sink the scan; core rules still apply.
                language_globs = {}
    return {
        "profile": profile,
        "rule_dirs": rule_dirs,
        "excludes_re": excludes_re,
        "language_globs": language_globs,
    }


# --- classification helpers ---------------------------------------------------

# (leading keyword in the matched text) -> kind. Ordered longest-first so
# "async def" wins over "def". Deterministic and language-agnostic.
_KIND_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("async def", "function"), ("def ", "function"),
    ("pub async fn", "function"), ("pub fn", "function"), ("fn ", "function"),
    ("export async function", "function"), ("export function", "function"),
    ("export class", "class"), ("class ", "class"),
    ("pub struct", "struct"), ("struct ", "struct"),
    ("export interface", "interface"), ("interface ", "interface"),
    ("export enum", "enum"), ("pub enum", "enum"), ("enum ", "enum"),
    ("pub trait", "trait"), ("trait ", "trait"),
    ("export type", "type"), ("type ", "type"),
    ("namespace ", "namespace"),
    ("virtual ", "method"),
    ("UCLASS", "uclass"), ("USTRUCT", "ustruct"), ("UINTERFACE", "uinterface"),
    ("UENUM", "uenum"), ("UFUNCTION", "ufunction"), ("UPROPERTY", "uproperty"),
)


def _kind_from(text: str, rule_id: str) -> str:
    """Deterministic kind from the matched text (falls back to the rule id)."""
    stripped = text.lstrip()
    for kw, kind in _KIND_KEYWORDS:
        if stripped.startswith(kw):
            return kind
    if "=" in text and rule_id.endswith("public-api"):
        return "variable"
    return "symbol"


def _visibility(name: str) -> str:
    return "private" if name.startswith("_") else "public"


def _signature(text: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first[:_SIG_MAX]


# --- ast-grep path ------------------------------------------------------------

def _parse_matches(raw: list, source_of_truth: str) -> list[dict]:
    """Turn ast-grep --json matches into the frozen symbol shape."""
    out: list[dict] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        meta = ((m.get("metaVariables") or {}).get("single") or {})
        name_node = meta.get("NAME") or {}
        text = m.get("text") or ""
        name = (name_node.get("text") or "").strip()
        if not name:
            # UE macro rules (UFUNCTION/UPROPERTY) capture no NAME — the macro
            # keyword is the useful token; the method name is recovered downstream.
            name = _signature(text).split("(")[0].strip() or text.strip()[:40]
        rule_id = m.get("ruleId") or ""
        start_line = (((m.get("range") or {}).get("start") or {}).get("line"))
        out.append({
            "name": name,
            "kind": _kind_from(text, rule_id),
            "file": m.get("file") or "",
            "line": (start_line + 1) if isinstance(start_line, int) else 0,
            "signature": _signature(text),
            "visibility": _visibility(name),
            "source_of_truth": source_of_truth,
            "lang": (m.get("language") or "").lower(),
            "rule": rule_id,
        })
    return out


def _chunk_paths(files: list[str], budget: int = _ARG_BUDGET):
    """Yield *files* in batches whose total char length stays under *budget*, so a
    large universe cannot blow past the OS argument-length limit (ARG_MAX) when
    handed to ast-grep as positional PATHS."""
    batch: list[str] = []
    size = 0
    for f in files:
        if batch and size + len(f) + 1 > budget:
            yield batch
            batch, size = [], 0
        batch.append(f)
        size += len(f) + 1
    if batch:
        yield batch


def _run_astgrep(root: Path, ruleset: dict, astgrep_path: str,
                 files: list[str]) -> list[dict]:
    """Run ast-grep over *files* (relative to *root*) with a merged temp sgconfig,
    one or more invocations chunked under ``_ARG_BUDGET``.

    The temp config lists every resolved rule dir as an absolute ``ruleDirs`` entry
    and carries the profile's ``languageGlobs`` (so UE ``.h`` files scan as cpp).
    KLC-105: *files* is an EXPLICIT positional PATHS list — ast-grep never walks the
    tree on its own, so it can never see a file outside the resolved universe.
    ``files=[]`` short-circuits to no invocation at all (an empty universe is a
    legitimate degrade case, C-005). Raises on a non-zero exit / missing binary so
    the caller can degrade.
    """
    if not files:
        return []
    import yaml
    cfg = {"ruleDirs": ruleset["rule_dirs"]}
    if ruleset["language_globs"]:
        cfg["languageGlobs"] = ruleset["language_globs"]
    with tempfile.NamedTemporaryFile(
        "w", suffix=".yml", delete=False, encoding="utf-8"
    ) as fh:
        yaml.safe_dump(cfg, fh)
        cfg_path = fh.name
    try:
        raw: list = []
        # D-004 codex verified: ast-grep 0.42.1's `scan [OPTIONS] [PATHS]...`
        # accepts multiple positional paths; a file that no longer exists on disk
        # (git may index a deleted-but-uncommitted path) is skipped rather than
        # failing the whole invocation.
        present = [f for f in files if (root / f).is_file()]
        for batch in _chunk_paths(present):
            r = subprocess.run(
                [astgrep_path, "scan", "--config", cfg_path, "--json", *batch],
                capture_output=True, text=True, timeout=300, cwd=str(root),
            )
            if r.returncode != 0:
                raise RuntimeError(
                    f"ast-grep exit {r.returncode}: {r.stderr.strip()[:200]}")
            raw.extend(json.loads(r.stdout or "[]"))
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass
    return _parse_matches(raw, "ast_grep")


# --- regex fallback -----------------------------------------------------------

def _iter_source_files(root: Path, files: list[str], excludes_re: str,
                       suffixes: tuple[str, ...]):
    """KLC-105: iterate universe MEMBERS with a matching suffix, sorted — never an
    independent rglob walk. ``_HIDDEN_OR_NOISE`` and the profile ``excludes_re`` are
    kept as an extra filter (defense in depth / D-004 double guard): the universe
    already applied its own excludes, but a caller-supplied ``files`` list is not
    assumed to be pre-filtered."""
    excl = re.compile(excludes_re) if excludes_re else None
    for rel in sorted(files):
        if Path(rel).suffix not in suffixes:
            continue
        if _HIDDEN_OR_NOISE.search(rel):
            continue
        if excl and excl.search(rel):
            continue
        p = root / rel
        if not p.is_file():
            continue
        yield p, rel


def _regex_scan(root: Path, excludes_re: str, files: list[str]) -> list[dict]:
    """Lower-fidelity fallback: public defs/classes (py) and exports (ts)."""
    symbols: list[dict] = []
    for p, rel in _iter_source_files(root, files, excludes_re, (".py",)):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for rx, kind in ((_PY_DEF_RE, "function"), (_PY_CLASS_RE, "class")):
                mm = rx.match(line)
                if mm and not mm.group(1).startswith("_"):
                    symbols.append(
                        _regex_symbol(mm.group(1), kind, rel, i, line, "python"))
    for p, rel in _iter_source_files(root, files, excludes_re, (".ts", ".tsx")):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            mm = _TS_EXPORT_RE.match(line)
            if mm:
                symbols.append(
                    _regex_symbol(mm.group(2), mm.group(1), rel, i, line, "typescript"))
    return symbols


def _regex_symbol(name, kind, rel, line, text, lang) -> dict:
    return {
        "name": name, "kind": kind, "file": rel, "line": line,
        "signature": _signature(text), "visibility": _visibility(name),
        "source_of_truth": "regex", "lang": lang, "rule": "regex-fallback",
    }


# --- build --------------------------------------------------------------------

def _drop_excluded(symbols: list[dict], excludes_re: str) -> list[dict]:
    """Filter out symbols in profile-excluded / hidden / noise paths.

    FIX-1 (codex P2): ast-grep does not know the profile's excludes (``Binaries``,
    ``Intermediate``, ``Content``, ``ThirdParty``, … for UE), so the ast-grep path
    would pollute inventory.json with generated/vendor symbols. The regex fallback
    already filters at scan time; applying the SAME excludes here makes both paths
    honour the profile (and is a harmless no-op for the already-filtered regex path).
    """
    excl = re.compile(excludes_re) if excludes_re else None
    out = []
    for s in symbols:
        f = s.get("file", "")
        if excl and excl.search(f):
            continue
        if _HIDDEN_OR_NOISE.search(f):
            continue
        out.append(s)
    return out


def _sort_key(s: dict) -> tuple:
    return (s["file"], s["line"], s["name"], s["rule"])


def inventory_coverage_verdicts(symbols: list[dict], structural: dict | None) -> list[dict]:
    """One coverage verdict PER LANGUAGE present in `structural.languages`
    (KLC-106 AC-7, D-005): distinct files carrying at least one symbol over
    that language's file count. A single project-wide ratio would be diluted
    by documentation/config files and would hide exactly the failure this
    metric exists to catch — one language's rule set matching nothing while
    another language's symbols keep the ratio healthy."""
    grouped = _inv.symbols_by_language({"symbols": symbols})
    verdicts = []
    for lang in sorted((structural or {}).get("languages") or {}):
        files_with_symbols = {s.get("file") for s in grouped.get(lang, ())}
        verdicts.append(index_coverage.verdict(
            f"inventory:{lang}", "inventory.json", len(files_with_symbols),
            index_coverage.universe_for(lang, structural),
            metric="files-with-symbols"))
    return verdicts


def build_inventory(root: Path, ruleset: dict, astgrep_path: str | None,
                    files: list[str] | None = None,
                    structural: dict | None = None) -> dict:
    """Deterministically inventory *root*. Pure w.r.t. (root, ruleset, astgrep_path,
    files): no timestamp, byte-identical on re-run (AC-11).

    ``files`` (KLC-105) is the resolved universe (relative posix paths) to scan. When
    ``None`` the universe is resolved HERE via ``file_universe.resolve(root)`` — a
    builder invoked without a prebuilt ``structural.json`` still refuses to walk on
    its own; it falls through to the SAME resolver ``file_scanner.py`` uses, never a
    private ``rglob``/``scan --config . .``.

    ``astgrep_path=None`` (or an ast-grep failure) → regex fallback with a note in
    ``errors[]`` and ``source_of_truth`` marked ``regex`` per language touched.

    ``structural`` (KLC-106 AC-7, optional and additive): when given, one
    coverage verdict per language present in ``structural.languages`` is
    appended to ``errors[]`` — see ``inventory_coverage_verdicts``.
    """
    errors: list[str] = []
    notes: list[str] = []
    symbols: list[dict] = []
    sot: dict[str, str] = {}

    universe = files if files is not None else file_universe.resolve(root)["files"]

    used_astgrep = False
    if astgrep_path:
        try:
            symbols = _run_astgrep(root, ruleset, astgrep_path, universe)
            used_astgrep = True
        except Exception as exc:  # missing binary, bad rule, timeout, bad JSON
            errors.append(f"ast-grep unavailable/failed ({exc}); regex fallback")
            symbols = []
    else:
        errors.append("ast-grep not resolved; regex fallback (lower fidelity)")

    if not used_astgrep:
        symbols = _regex_scan(root, ruleset.get("excludes_re", ""), universe)
        notes.append("symbols from regex fallback — visibility/kind less precise "
                     "than ast-grep; source_of_truth=regex")

    # FIX-1: apply the profile excludes on BOTH paths (ast-grep does not know them).
    symbols = _drop_excluded(symbols, ruleset.get("excludes_re", ""))

    # KLC-105 D-004 double guard: closure holds even if ast-grep re-expands an
    # argument (e.g. a directory alias) beyond what was requested.
    member = set(universe)
    symbols = [s for s in symbols if s.get("file") in member]

    for s in symbols:
        sot.setdefault(s["lang"] or "unknown", s["source_of_truth"])

    symbols.sort(key=_sort_key)
    if structural is not None:
        errors.extend(inventory_coverage_verdicts(symbols, structural))
    return {
        "root": str(root),
        "profile": ruleset.get("profile", ""),
        "source_of_truth": dict(sorted(sot.items())),
        "symbols": symbols,
        "errors": errors,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic no-LLM symbol inventory")
    # FIX-5: default to project_root() (PROJECT_ROOT from env, C-002), not cwd.
    ap.add_argument("--root", type=Path, default=project_root())
    ap.add_argument("--profile", default=None,
                    help="advisory only; the active profile is resolved from config")
    ap.add_argument("--out", type=Path, default=klc_index_dir() / "inventory.json")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        sys.stderr.write(f"deterministic_inventory: not a directory: {root}\n")
        return 2

    ruleset = resolve_ruleset()
    astgrep = _tools.resolve_tool("ast-grep")
    structural = index_coverage.load_json_or_none(
        klc_index_dir() / "structural.json")
    result = build_inventory(root, ruleset, str(astgrep) if astgrep else None,
                              structural=structural)

    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for e in result["errors"]:
        sys.stderr.write(f"deterministic_inventory: warning: {index_coverage.render_error(e)}\n")
    print(f"deterministic_inventory: wrote {len(result['symbols'])} symbol(s) to "
          f"{args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
