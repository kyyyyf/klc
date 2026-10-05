#!/usr/bin/env python3
"""review_signals.py — KLC-175: the model-free signals that decide layer 2.

One place owns what a diff "signals": the named triggers (public API,
config/persistence, security words, a new import edge) that used to live in
scripts/review.py, plus the sentinel / critical-tier / hot-path signals the
three-layer cascade adds. `review_cascade.decide` and `scripts/review.py`
both read these, so the in-client and the headless path plan the same
specialists (no model call, no I/O beyond reading modules.json).
"""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

# Built-in diff-regex patterns for named structured triggers.
# `^\+(?!\+)` matches added lines only (excludes `+++` header lines).
# `changed_public_api`: an added TOP-LEVEL python `def`/`class` whose name does
# not start with `_`, or an added `export` / `pub` / `public` declaration.
# `signals()` applies it per file and only to code files (not tests, not prose).
TRIGGER_PATTERNS: dict[str, str] = {
    "changed_public_api": (
        r"^\+(?!\+)(?:(?:async +)?(?:def|class) +(?!_)\w"
        r"|\s*(?:export |pub fn |pub struct |pub enum |public ))"
    ),
    "config_or_persistence_change": (
        r"(\.ya?ml|\.toml|\.ini|\.env|\.cfg|migration|schema|DATABASE|DB_URL"
        r"|\.sql|persistence|config\.)"
    ),
    "security_sensitive_diff": (
        r"\b(password|secret|token|auth|crypt|cipher|hmac|jwt|oauth|api_key"
        r"|access_key|private_key)\b"
    ),
}

# deep-impact keeps its four historical triggers ("as today").
DEEP_IMPACT_TRIGGERS = ("changed_public_api", "config_or_persistence_change",
                        "security_sensitive_diff", "dependency_edge_added")

# The marker that flags an added line as a hot path: a trailing `# perf:hot`
# (or `// perf:hot`) comment on a line that also has code. A comment-only line,
# a docs line and a string literal in prose do not count.
HOT_MARKER = re.compile(r"(?:#|//)\s*perf:hot\b")

# Files that are never code for the public-API and hot-marker signals.
_PROSE_EXT = (".md", ".rst", ".txt", ".yml", ".yaml", ".json", ".toml", ".ini",
              ".cfg", ".env", ".j2", ".sql", ".lock", ".csv")

# The signals `signals()` returns, in a fixed order. Each is True / False, or
# None when it could not be evaluated (a scanner or the classifier failed).
SIGNAL_NAMES = ("changed_public_api", "config_or_persistence_change",
                "security_sensitive_diff", "dependency_edge_added",
                "sentinel_hit", "critical_tier", "hot_path", "deep_impact")


def is_code_file(path: str) -> bool:
    """True for a source file: not prose or data, not a test."""
    low = path.lower()
    if low.endswith(_PROSE_EXT):
        return False
    parts = low.split("/")
    base = parts[-1]
    if "tests" in parts[:-1] or "test" in parts[:-1]:
        return False
    return not (base.startswith("test_") or "_test." in base or ".test." in base
                or ".spec." in base)


def added_lines_by_file(diff_text: str) -> dict[str, list[str]]:
    """path -> the added lines (with their leading `+`) of that file's diff."""
    out: dict[str, list[str]] = {}
    cur = None
    for ln in (diff_text or "").splitlines():
        if ln.startswith("+++ "):
            name = ln[4:].split("\t")[0].strip()
            name = name[2:] if name.startswith("b/") else name
            cur = None if name == "/dev/null" else name
            if cur is not None:
                out.setdefault(cur, [])
        elif ln.startswith("diff --git "):
            cur = None
        elif cur is not None and ln.startswith("+") and not ln.startswith("+++"):
            out[cur].append(ln)
    return out


def grep_match(pattern: str, text: str) -> bool:
    try:
        return bool(re.search(pattern, text, re.MULTILINE))
    except re.error:
        return False


def dependency_edge_added(diff_text: str, modules_json_path: Path | None) -> bool:
    """True iff the diff adds an import of a named module in modules.json."""
    if modules_json_path is None or not Path(modules_json_path).exists():
        return False
    try:
        raw = json.loads(Path(modules_json_path).read_text(encoding="utf-8"))
        modules = raw.get("modules", [])
    except (OSError, json.JSONDecodeError):
        return False
    module_names = {m["name"] for m in modules if m.get("name")}
    if not module_names:
        return False
    import_re = re.compile(
        r"^\+(?!\+).*\b(?:import|require|from|include|use)\b[^;]*\b("
        + "|".join(re.escape(n) for n in sorted(module_names))
        + r")\b",
        re.MULTILINE,
    )
    return bool(import_re.search(diff_text))


def _changed_paths(diff_text: str) -> list[str]:
    out = []
    for m in re.finditer(r"^\+\+\+ (?:b/)?(\S+)", diff_text, re.MULTILINE):
        if m.group(1) != "/dev/null":
            out.append(m.group(1))
    return out


def changed_public_api(diff_text: str) -> bool:
    """An added public declaration in a code file (see TRIGGER_PATTERNS)."""
    pat = re.compile(TRIGGER_PATTERNS["changed_public_api"])
    return any(pat.search(ln) for path, lines in added_lines_by_file(diff_text).items()
               if is_code_file(path) for ln in lines)


def _hot_marker(diff_text: str) -> bool:
    for path, lines in added_lines_by_file(diff_text).items():
        if not is_code_file(path):
            continue
        for ln in lines:
            m = HOT_MARKER.search(ln)
            if m and ln[1:m.start()].strip():      # code before the comment
                return True
    return False


def hot_path(diff_text: str, cfg: dict) -> bool:
    """A changed file matches `cascade.specialists.performance.hot_path_globs`,
    or a code line carries the trailing `perf:hot` marker."""
    if _hot_marker(diff_text):
        return True
    perf = (((cfg or {}).get("specialists") or {}).get("performance") or {})
    globs = [g for g in (perf.get("hot_path_globs") or []) if isinstance(g, str)]
    if not globs:
        return False
    return any(fnmatch.fnmatch(p, g) for p in _changed_paths(diff_text) for g in globs)


def signals(diff_text: str, modules_json: Path | None, cfg: dict,
            file_tiers: dict | None, *, sentinel_hits: int | None = 0) -> dict:
    """The named signals of *diff_text*: True / False, or None (unevaluable).

    *cfg* is the `cascade` block of reviewers.yml; *file_tiers* is classify_tier's
    path -> tier map, or None when the classifier failed; *sentinel_hits* is the
    sentinel count, or None when the scan failed. A None signal is never read as
    "no risk": `review_cascade.specialists_for` and `scripts/review.py` plan the
    signal's specialist. An exception from a signal's own code makes that signal
    None too."""
    def _try(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001 — unevaluable, fail closed
            return None

    sig: dict = {name: _try(lambda p=pat: grep_match(p, diff_text))
                 for name, pat in TRIGGER_PATTERNS.items()}
    sig["changed_public_api"] = _try(lambda: changed_public_api(diff_text))
    sig["dependency_edge_added"] = _try(lambda: dependency_edge_added(diff_text, modules_json))
    sig["sentinel_hit"] = None if sentinel_hits is None else sentinel_hits > 0
    sig["critical_tier"] = (None if file_tiers is None
                            else any(t == "critical" for t in file_tiers.values()))
    sig["hot_path"] = _try(lambda: hot_path(diff_text, cfg))
    deep = [sig[n] for n in DEEP_IMPACT_TRIGGERS]
    sig["deep_impact"] = True if any(v is True for v in deep) else (
        None if any(v is None for v in deep) else False)
    return sig


def unevaluable(sig: dict) -> list[str]:
    """Names of the signals in *sig* that are None."""
    return [n for n, v in (sig or {}).items() if v is None]


def fired(sig: dict) -> list[str]:
    """Names of the signals in *sig* that are True (deep_impact is a union of
    others, listed only when it stands alone)."""
    return [n for n, v in (sig or {}).items() if v is True]


def all_unevaluable() -> dict:
    """What a whole-evaluation failure stands for: every signal None."""
    return {n: None for n in SIGNAL_NAMES}
