#!/usr/bin/env python3
"""review.py — drive the multi-agent code review.

Port of review.sh. Same two-mode contract:

  Offline (default): stage job cards, wait for a human / operator to
    fulfil them via Claude Code, re-enter to aggregate.

  Headless (RUN_LOCAL_SUBAGENTS=1 + REVIEW_RUNNER executable):
    dispatch every card through REVIEW_RUNNER in parallel, aggregate.

Output:
  - .klc/reports/pending-<TS>/   job cards + context bundle
  - .klc/reports/partials-<TS>/  sub-agent partials + diff.sha256 + profile.txt
  - .klc/reports/review-<TS>.md  final rendered report
  - Exit 0 = APPROVED, 1 = CHANGES REQUESTED.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
from _paths import (  # noqa: E402
    project_root, klc_dir, klc_knowledge_dir, klc_reports_dir,
)
from findings import aggregate, dedupe, sort_for_report, Finding  # noqa: E402
import file_scanner as _fs  # noqa: E402  (KLC-124 D-4: the one EXT_LANG source)
import handback  # noqa: E402  (KLC-127 AC-14/AC-22: validate + pool headless partials)


# --- logging -----------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[review] {msg}")


def die(msg: str, code: int = 2) -> int:
    sys.stderr.write(f"[review][err] {msg}\n")
    return code


# --- retention ---------------------------------------------------------------

def _prune_reports(reports_dir: Path, *,
                   partials_days: int, runs: int) -> None:
    """Delete partials-*/pending-* older than `partials_days` and
    all but the `runs` most-recent `review-*.md` files."""
    cutoff = time.time() - partials_days * 86400
    for child in reports_dir.iterdir():
        if not child.is_dir():
            continue
        if not (child.name.startswith("pending-") or
                child.name.startswith("partials-")):
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            pass
    reports = sorted(
        reports_dir.glob("review-*.md"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for old in reports[runs:]:
        try:
            old.unlink()
        except OSError:
            pass


# --- profile / module helpers ------------------------------------------------

def _resolve_profile_field(field: str) -> str:
    script = FRAMEWORK_ROOT / "core" / "skills" / "profile-resolve.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), "--field", field],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip()


def _resolve_diff(diff_arg: str, out_path: Path) -> bool:
    """`diff_arg` is a file path or a git ref. Write the unified diff
    to out_path. Returns True on success."""
    p = Path(diff_arg)
    if p.is_file():
        out_path.write_bytes(p.read_bytes())
        return True
    root = project_root()
    r = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", diff_arg],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        return False
    r = subprocess.run(
        ["git", "-C", str(root), "diff", diff_arg],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        return False
    out_path.write_text(r.stdout, encoding="utf-8")
    return True


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --- CLAUDE.md context bundle ------------------------------------------------

def _affected_modules(diff_file: Path, modules_json: Path) -> list[str]:
    script = FRAMEWORK_ROOT / "core" / "skills" / "diff-modules.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), str(diff_file),
             "--modules", str(modules_json)],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


def _modules_index(modules_json: Path) -> dict[str, dict]:
    """Return a map name → {path, doc_filename}."""
    if not modules_json.exists():
        return {}
    try:
        data = json.loads(modules_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    idx: dict[str, dict] = {}
    for m in data.get("modules") or []:
        name = m.get("name")
        if not name:
            continue
        idx[name] = {
            "path":         m.get("path", ""),
            "doc_filename": m.get("doc_filename") or "CLAUDE.md",
        }
    return idx


def _write_ctx_bundle(ctx_path: Path, *,
                      root: Path,
                      modules_idx: dict[str, dict],
                      affected: list[str]) -> None:
    """Build claude-md-context.md: root CLAUDE.md + each affected
    module's per-module doc, with begin/end markers."""
    chunks: list[str] = []
    root_claude = root / "CLAUDE.md"
    if root_claude.exists():
        chunks.append("<!-- BEGIN root CLAUDE.md -->")
        chunks.append(root_claude.read_text(encoding="utf-8").rstrip("\n"))
        chunks.append("<!-- END root CLAUDE.md -->")
    for name in affected:
        info = modules_idx.get(name)
        if not info:
            continue
        mpath = info["path"]
        doc = root / mpath / info["doc_filename"]
        if not doc.exists():
            continue
        chunks.append(f"<!-- BEGIN module {name} ({mpath}) -->")
        chunks.append(doc.read_text(encoding="utf-8").rstrip("\n"))
        chunks.append(f"<!-- END module {name} -->")
    ctx_path.write_text("\n".join(chunks) + "\n", encoding="utf-8")


def _collect_adrs(root: Path,
                  modules_idx: dict[str, dict],
                  affected: list[str]) -> tuple[list[Path], dict[str, str]]:
    """Collect ADRs from ## ADRs sections in CLAUDE.md files.
    Returns (adr_paths, adr_inlined).

    Phase 2.3: Parse ## ADRs or ## Architecture Decision Records sections,
    resolve markdown links [ADR-NNN](path), inline contents.
    """
    import re

    adr_candidates: list[Path] = []

    # Gather CLAUDE.md files to scan
    claude_mds: list[Path] = []
    root_claude = root / "CLAUDE.md"
    if root_claude.exists():
        claude_mds.append(root_claude)
    for name in affected:
        info = modules_idx.get(name)
        if not info:
            continue
        doc = root / info["path"] / info["doc_filename"]
        if doc.exists():
            claude_mds.append(doc)

    # Parse each CLAUDE.md for ## ADRs section
    for md_path in claude_mds:
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = text.splitlines()
        in_adr_section = False
        for line in lines:
            stripped = line.strip()
            if stripped in ("## ADRs", "## Architecture Decision Records"):
                in_adr_section = True
                continue
            if in_adr_section:
                if stripped.startswith("## "):  # next section
                    break
                # Match markdown links: [ADR-NNN](path) or [ADR-NNN: title](path)
                m = re.match(r"^-?\s*\[ADR-\d+[^\]]*\]\(([^)]+)\)", stripped)
                if m:
                    link_target = m.group(1)
                    # Resolve relative to the CLAUDE.md directory
                    resolved = (md_path.parent / link_target).resolve()
                    if resolved.exists():
                        adr_candidates.append(resolved)

    # Deduplicate by absolute path
    adr_paths = sorted(set(adr_candidates), key=lambda p: p.name)

    # Inline contents
    adr_inlined: dict[str, str] = {}
    for p in adr_paths:
        try:
            adr_inlined[str(p)] = p.read_text(encoding="utf-8")
        except OSError:
            pass

    return adr_paths, adr_inlined


# --- ticket meta reader ------------------------------------------------------

def _read_ticket_meta(spec_path: Path) -> dict:
    """Read meta.json for the ticket whose spec is at spec_path, or {} on error."""
    try:
        meta_path = spec_path.parent / "meta.json"
        if meta_path.exists():
            return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# --- reviewer discovery ------------------------------------------------------

def _load_reviewers() -> tuple[list[dict], list[dict]]:
    """Return (always[], conditional[]) from the profile manifest.
    Each conditional entry: {name, path, filter?, trigger?, enabled_for_tracks?, triggers?}.
    The legacy single-string trigger: and the new structured triggers: list are
    both preserved; _evaluate_conditional_trigger handles both."""
    raw = _resolve_profile_field("reviewers")
    if not raw:
        return [], []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [], []

    def _flatten(lst, include_trigger: bool) -> list[dict]:
        out: list[dict] = []
        for r in lst or []:
            path = r.get("path", "")
            if not path:
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            entry = {"name": name, "path": path,
                     "filter": r.get("filter") or ""}
            if include_trigger:
                entry["trigger"] = r.get("trigger") or ""
                # structured trigger extensions (KLC-025)
                if r.get("enabled_for_tracks"):
                    entry["enabled_for_tracks"] = list(r["enabled_for_tracks"])
                if r.get("triggers"):
                    entry["triggers"] = list(r["triggers"])
            out.append(entry)
        return out

    return _flatten(data.get("always"), False), _flatten(data.get("conditional"), True)


# Built-in diff-regex patterns for named structured triggers.
# Use ^\+(?!\+) to match added lines only (excludes +++ diff header lines).
_TRIGGER_PATTERNS: dict[str, str] = {
    "changed_public_api": (
        r"^\+(?!\+).*\b(def |class |export |pub fn |pub struct |pub enum |public )"
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


def _trigger_dependency_edge_added(diff_text: str, modules_json_path: Path | None) -> bool:
    """Return True iff the diff adds an import of a named module in modules.json."""
    if modules_json_path is None or not modules_json_path.exists():
        return False
    try:
        raw = json.loads(modules_json_path.read_text(encoding="utf-8"))
        modules = raw.get("modules", [])
    except (OSError, json.JSONDecodeError):
        return False
    if not modules:
        return False
    module_names = {m["name"] for m in modules if m.get("name")}
    if not module_names:
        return False
    # Look for added import lines that reference a known module name
    import_re = re.compile(
        r"^\+(?!\+).*\b(?:import|require|from|include|use)\b[^;]*\b("
        + "|".join(re.escape(n) for n in sorted(module_names))
        + r")\b",
        re.MULTILINE,
    )
    return bool(import_re.search(diff_text))


def _evaluate_conditional_trigger(
    entry: dict,
    diff_text: str,
    meta_track: str,
    modules_json_path: Path | None,
) -> bool:
    """Return True iff this conditional reviewer should run.

    Evaluation order:
    1. enabled_for_tracks: if set, meta_track must be in the list.
    2. triggers (structured list): any named trigger fires → True.
    3. trigger (legacy regex string): if no structured triggers, fall back.
    4. Neither specified → always run (backward compat).
    """
    # 1. Track gate
    allowed_tracks = entry.get("enabled_for_tracks")
    if allowed_tracks is not None and meta_track not in allowed_tracks:
        return False

    # 2. Structured triggers (OR semantics)
    structured = entry.get("triggers")
    if structured:
        for trigger_name in structured:
            if trigger_name == "dependency_edge_added":
                if _trigger_dependency_edge_added(diff_text, modules_json_path):
                    return True
            else:
                pattern = _TRIGGER_PATTERNS.get(trigger_name)
                if pattern and _grep_match(pattern, diff_text):
                    return True
        return False  # structured triggers specified but none fired

    # 3. Legacy single-regex trigger
    trig = entry.get("trigger", "")
    if trig:
        return _grep_match(trig, diff_text)

    # 4. No trigger at all → always run
    return True


def _grep_match(pattern: str, text: str) -> bool:
    try:
        return bool(re.search(pattern, text, re.MULTILINE))
    except re.error:
        return False


def _validate_regex(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


# --- job-card emission -------------------------------------------------------

def _extract_rules_catalog(prompt_path: Path) -> str:
    """Extract the `## Rules` section from a reviewer prompt (Phase 1.4).

    Returns the section content as a string, or empty string if not found.
    """
    if not prompt_path.exists():
        return ""
    text = prompt_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    in_rules = False
    catalog_lines: list[str] = []
    for line in lines:
        if line.strip().startswith("## Rules"):
            in_rules = True
            continue
        if in_rules:
            if line.strip().startswith("## "):  # next section
                break
            catalog_lines.append(line)
    return "\n".join(catalog_lines).strip()


def _build_callgraph_slice(diff_path: Path, pending_dir: Path) -> Path | None:
    """Phase 4.6: Build call graph slice for changed files.

    Extracts changed files from diff, checks for available call graphs,
    returns aggregated slice JSON for reviewers.

    Returns None if no call graphs available or diff empty.
    """
    # Parse diff to get changed files
    changed_files: set[str] = set()
    if not diff_path.exists():
        return None

    try:
        text = diff_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    for line in text.splitlines():
        if line.startswith("+++ b/"):
            file_path = line[6:].strip()
            changed_files.add(file_path)

    if not changed_files:
        return None

    # Detect languages from changed files, via the ONE canonical
    # extension->language table (file_scanner.EXT_LANG, KLC-124 D-4) —
    # this used to hand-author its own second copy, which mapped .js/.jsx
    # to "typescript" where EXT_LANG says "javascript"; no
    # callgraph/{javascript,typescript}.json builder exists for either name
    # today, so both always fall through to `available_graphs` being empty
    # regardless — the correction is behaviourally inert until a JS/TS
    # call-graph builder exists.
    lang_to_files: dict[str, list[str]] = {}
    for fpath in changed_files:
        ext = Path(fpath).suffix.lower().lstrip(".")
        lang = _fs.EXT_LANG.get(ext)
        if lang:
            lang_to_files.setdefault(lang, []).append(fpath)

    if not lang_to_files:
        return None

    # Check which call graphs are available
    index_dir = klc_dir() / "index" / "callgraph"
    available_graphs: dict[str, dict] = {}

    for lang in lang_to_files:
        cg_path = index_dir / f"{lang}.json"
        if cg_path.exists():
            try:
                with cg_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                available_graphs[lang] = data.get("symbols", {})
            except (OSError, json.JSONDecodeError):
                pass

    if not available_graphs:
        return None

    # Aggregate: for each changed file, find symbols defined in that file
    all_symbols: list[dict] = []
    for lang, cg in available_graphs.items():
        for file_path in lang_to_files.get(lang, []):
            for sym_name, sym_data in cg.items():
                if sym_data.get("file") == file_path:
                    entry = sym_data.copy()
                    entry["qualified_name"] = sym_name
                    all_symbols.append(entry)

    if not all_symbols:
        return None

    # Write aggregated slice
    slice_path = pending_dir / "callgraph_slice.json"
    output = {
        "mode": "aggregated",
        "changed_files": sorted(changed_files),
        "available_languages": list(available_graphs.keys()),
        "symbols": all_symbols,
        "stats": {
            "changed_files_count": len(changed_files),
            "symbols_in_changed_files": len(all_symbols),
        }
    }

    slice_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return slice_path


def _write_job_card(card: Path, *,
                    reviewer: str,
                    prompt: str,
                    diff: Path,
                    spec: Path,
                    context: Path,
                    allowlist: Path,
                    severity_rubric: Path,
                    rule_catalog_content: str,
                    adr_context: Path | None,
                    test_plan: Path | None,
                    callgraph_slice: Path | None,
                    partial: Path) -> None:
    # Phase 1.4: write rule_catalog to a temp file next to the card
    rule_catalog_path = card.parent / f"rule_catalog-{reviewer}.txt"
    rule_catalog_path.write_text(rule_catalog_content, encoding="utf-8")

    # Phase 2.3: optional ADR and test-plan context
    adr_line = f"- adr_context:       {adr_context}\n" if adr_context else ""
    test_plan_line = f"- test_plan:         {test_plan}\n" if test_plan else ""
    # Phase 4.6: optional call graph slice
    callgraph_line = f"- callgraph_slice:   {callgraph_slice}\n" if callgraph_slice else ""

    body = (
        f"# Review sub-agent job: {reviewer}\n\n"
        f"Prompt file: {prompt}\n"
        "Inputs:\n"
        f"- diff:              {diff}\n"
        f"- spec:              {spec}\n"
        f"- claude_md_context: {context}\n"
        f"- allowlist:         {allowlist}\n"
        f"- severity_rubric:   {severity_rubric}\n"
        f"- rule_catalog:      {rule_catalog_path}\n"
        f"{adr_line}"
        f"{test_plan_line}"
        f"{callgraph_line}"
        "\n"
        "Before emitting any finding, read the allowlist. If a finding matches\n"
        f"an entry whose `reviewer` is \"{reviewer}\" or \"*\", downgrade to "
        "INFO and append\n"
        "`(allowlisted: <reason>)` to the title, per the prompt's Hard rules.\n"
        "\n"
        f"Write TWO outputs (Phase 1.2):\n"
        f"1. findings.json to {partial.parent / reviewer / 'findings.json'}\n"
        f"2. Markdown partial to {partial}\n"
        "\n"
        "Required trailer (last line of the markdown partial):\n"
        "  ISSUES_TOTAL=<n> ISSUES_BLOCKING=<n>\n"
    )

    # Lint operator-controlled injected text (allowlist reasons) for pre-judgment
    # directives. Committed reviewer prompts are out of scope; reason strings in
    # the allowlist are user-written and get echoed verbatim by sub-agents.
    from core.skills.lint_review_prompts import lint_text as _lint
    try:
        from _yaml import parse as _yaml_parse
        _raw = _yaml_parse(allowlist.read_text(encoding="utf-8")) or {}
        _entries = _raw.get("entries") or [] if isinstance(_raw, dict) else []
        _reasons = " ".join(
            str(e.get("reason", ""))
            for e in _entries
            if isinstance(e, dict) and e.get("reason")
        )
        if _reasons:
            _hits = _lint(_reasons)
            if _hits:
                sys.stderr.write(
                    f"[no-pre-judgment] allowlist reasons contain pre-judgment "
                    f"directive: {_hits}\n"
                )
    except Exception:
        pass

    card.write_text(body, encoding="utf-8")


def _write_skip_partial(partial: Path, reviewer: str) -> None:
    """Conditional reviewer with no trigger match: still emit a partial
    so the aggregator shows a per-reviewer row (skipped)."""
    partial.write_text(
        f"## {reviewer} Review\n\n"
        "_reviewer skipped (conditional trigger not matched)_\n\n"
        "ISSUES_TOTAL=0 ISSUES_BLOCKING=0\n",
        encoding="utf-8",
    )


# --- per-reviewer diff / ctx trimming ----------------------------------------

def _filter_diff(full_diff: Path, pattern: str, out: Path) -> bool:
    script = FRAMEWORK_ROOT / "core" / "skills" / "filter-diff.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), str(full_diff), pattern, str(out)],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


_HEAD_SLICE_RE = re.compile(
    r"<!--\s*BEGIN:\s*head\s*-->(.*?)<!--\s*END:\s*head\s*-->", re.DOTALL,
)


def _root_head_slice(root_claude: Path) -> str:
    """Return just the `<!-- BEGIN: head --> ... <!-- END: head -->`
    section of root CLAUDE.md, or the whole file if those markers are
    absent."""
    if not root_claude.exists():
        return ""
    text = root_claude.read_text(encoding="utf-8")
    m = _HEAD_SLICE_RE.search(text)
    return m.group(1).strip() if m else text


def _write_reviewer_ctx(out: Path, *,
                        root_claude: Path,
                        modules_idx: dict[str, dict],
                        affected: list[str],
                        project_root_dir: Path) -> None:
    chunks: list[str] = []
    head = _root_head_slice(root_claude)
    if head:
        chunks.append(head)
    for name in affected:
        info = modules_idx.get(name)
        if not info:
            continue
        doc = project_root_dir / info["path"] / info["doc_filename"]
        if not doc.exists():
            continue
        chunks.append(f"\n<!-- BEGIN module {name} ({info['path']}) -->")
        chunks.append(doc.read_text(encoding="utf-8").rstrip("\n"))
        chunks.append(f"<!-- END module {name} -->")
    out.write_text("\n".join(chunks) + "\n", encoding="utf-8")


# --- partial parsing + aggregation ------------------------------------------

_SEVERITY_RE = re.compile(r"^###\s+\[(?P<sev>[A-Z]+)\]\s+(?P<rest>.+)$")
_TRAILER_RE  = re.compile(r"ISSUES_TOTAL=(\d+)\s+ISSUES_BLOCKING=(\d+)")
_HUNK_RE     = re.compile(r"^@@ -(?P<ostart>\d+)(?:,\d+)? \+(?P<nstart>\d+)(?:,\d+)? @@")
_FILE_LINE_RE = re.compile(r"([\w./\-]+\.\w+):(\d+)")


def _parse_diff_scope(diff_path: Path) -> dict[str, dict[str, set[int]]]:
    """For each touched file: (new-side line numbers, old-side line
    numbers). A reviewer's `file:line` is in-scope if the line lands
    in either set."""
    scope: dict[str, dict[str, set[int]]] = {}
    if not diff_path.exists():
        return scope
    current_file: str | None = None
    new_line: int | None = None
    old_line: int | None = None
    try:
        text = diff_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return scope
    for line in text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            scope.setdefault(current_file, {"new": set(), "old": set()})
            continue
        if line.startswith("--- ") or line.startswith("diff "):
            current_file = None
            continue
        m = _HUNK_RE.match(line)
        if m and current_file is not None:
            new_line = int(m.group("nstart"))
            old_line = int(m.group("ostart"))
            continue
        if current_file is None or new_line is None or old_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            scope[current_file]["new"].add(new_line)
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            scope[current_file]["old"].add(old_line)
            old_line += 1
        elif line.startswith(" "):
            new_line += 1
            old_line += 1
    return scope


def _classify_scope(diff_scope: dict[str, dict[str, set[int]]],
                    title: str) -> bool | None:
    """In-scope (True), out-of-scope (False), unclassifiable (None)."""
    m = _FILE_LINE_RE.search(title)
    if not m:
        return None
    file, line_s = m.group(1), int(m.group(2))
    candidates = [
        f for f in diff_scope
        if f == file or f.endswith("/" + file) or file.endswith("/" + f)
    ]
    if not candidates:
        return False
    best = max(candidates, key=len)
    buckets = diff_scope[best]
    return line_s in buckets["new"] or line_s in buckets["old"]


def _parse_partial(path: Path,
                   diff_scope: dict[str, dict[str, set[int]]]) -> dict:
    """Parse a reviewer partial (Phase 1.3: JSON-first, then markdown fallback).

    Expected structure:
      partials-<TS>/<reviewer>/findings.json  (Phase 1.2 structured output)
      partials-<TS>/<reviewer>.partial.md      (legacy markdown, read for trailer check)

    Returns dict with keys: total, blocking, issues, raw, trailer_mismatch, out_of_scope.
    """
    # Phase 1.3: read findings.json if present
    findings_json_path = path.parent / path.stem.replace(".partial", "") / "findings.json"
    if not findings_json_path.exists():
        # Fallback: legacy markdown-only partial (pre-Phase1)
        # This block preserved for backwards compat during transition
        if not path.exists():
            return {"total": 0, "blocking": 0, "issues": [], "raw": "",
                    "trailer_mismatch": None, "out_of_scope": 0}
        text = path.read_text(encoding="utf-8")
        issues: list[dict] = []
        for line in text.splitlines():
            m = _SEVERITY_RE.match(line.strip())
            if not m:
                continue
            title = m.group("rest").strip()
            scope = _classify_scope(diff_scope, title)
            issues.append({
                "severity": m.group("sev"),
                "title":    title,
                "line":     line,
                "suspect_out_of_scope": (scope is False),
            })
        total    = sum(1 for i in issues if i["severity"] != "INFO")
        blocking = sum(1 for i in issues if i["severity"] in ("CRITICAL", "HIGH"))
        out_of_scope = sum(1 for i in issues if i["suspect_out_of_scope"])
        return {
            "total":            total,
            "blocking":         blocking,
            "issues":           issues,
            "raw":              text,
            "trailer_mismatch": None,
            "out_of_scope":     out_of_scope,
        }

    # New path: load findings.json via findings.py
    reviewer_name = findings_json_path.parent.name
    try:
        with findings_json_path.open("r", encoding="utf-8") as f:
            findings_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"review: {findings_json_path.name}: malformed JSON: {e}\n")
        return {"total": 0, "blocking": 0, "issues": [], "raw": "",
                "trailer_mismatch": None, "out_of_scope": 0}
    if not isinstance(findings_data, list):
        sys.stderr.write(f"review: {findings_json_path.name}: not a JSON list\n")
        return {"total": 0, "blocking": 0, "issues": [], "raw": "",
                "trailer_mismatch": None, "out_of_scope": 0}
    # KLC-127 AC-14: validate the WHOLE partial before trusting any of it — an
    # old-shape or otherwise invalid findings.json is left OUT of the report
    # entirely (one note naming the reviewer and its errors), never partially
    # accepted.
    errors = handback.validate_findings("code-review", findings_data)
    if errors:
        sys.stderr.write(
            f"review: partial {reviewer_name} left out: {'; '.join(errors[:3])}\n")
        return {"total": 0, "blocking": 0, "issues": [], "raw": "",
                "trailer_mismatch": None, "out_of_scope": 0}
    try:
        findings_list = [
            Finding.from_dict({**d, "reviewer": reviewer_name, "kind": "code-review"})
            for d in findings_data
        ]
    except (KeyError, TypeError, ValueError) as e:
        # Validated above, so this should not happen (F-102) — kept as a
        # fail-closed safety net rather than an assumption.
        sys.stderr.write(f"review: {findings_json_path.name}: malformed entry: {e}\n")
        return {"total": 0, "blocking": 0, "issues": [], "raw": "",
                "trailer_mismatch": None, "out_of_scope": 0}

    # Convert Finding objects to legacy dict format expected by caller
    issues: list[dict] = []
    for f in findings_list:
        scope = _classify_scope(diff_scope, f"{f.file}:{f.line}")
        issues.append({
            "severity":             f.severity,
            "title":                f"{f.title} — {f.file}:{f.line}",
            "line":                 f"### [{f.severity}] {f.title} — {f.file}:{f.line}",  # legacy format for rendering
            "suspect_out_of_scope": (scope is False),
            "finding":              f,  # preserve full Finding object for future use
        })

    total    = sum(1 for i in issues if i["severity"] != "INFO")
    blocking = sum(1 for i in issues if i["severity"] in ("CRITICAL", "HIGH"))
    out_of_scope = sum(1 for i in issues if i["suspect_out_of_scope"])

    # Read markdown partial for trailer check (Phase 1.3 integrity check)
    trailer_mismatch = None
    raw_text = ""
    if path.exists():
        raw_text = path.read_text(encoding="utf-8")
        m = _TRAILER_RE.search(raw_text)
        if m:
            t_total = int(m.group(1))
            t_blocking = int(m.group(2))
            if (t_total, t_blocking) != (total, blocking):
                trailer_mismatch = (
                    f"trailer TOTAL={t_total} BLOCKING={t_blocking}, "
                    f"JSON findings TOTAL={total} BLOCKING={blocking}"
                )
                sys.stderr.write(f"review: {path.name}: {trailer_mismatch}\n")

    return {
        "total":            total,
        "blocking":         blocking,
        "issues":           issues,
        "raw":              raw_text,
        "trailer_mismatch": trailer_mismatch,
        "out_of_scope":     out_of_scope,
    }


def _reviewer_label(key: str) -> str:
    return " ".join(
        w.upper() if len(w) <= 2 else w.capitalize()
        for w in key.split("-")
    )


def _is_skip_partial(rev: dict) -> bool:
    if rev["total"] != 0 or rev["blocking"] != 0 or rev["issues"]:
        return False
    return "reviewer skipped" in (rev.get("raw") or "")


def _is_failed_partial(path: Path) -> bool:
    """KLC-120 D-015: a synthetic CRITICAL partial core/skills/runner.py
    writes on a dispatch failure — its first non-blank line is the heading
    `## Agent run failed — <phase>`. Such a partial exists on disk but is
    NOT an executed pass (AC-3's writer never recorded an attempt for it
    either, D-008)."""
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith("## Agent run failed —")
    return False


# --- partial-reuse -----------------------------------------------------------

def _try_reuse_partials(reports_dir: Path, *,
                        reviewers: list[str],
                        current_hash: str,
                        current_profile: str) -> Path | None:
    """Return the directory of a reusable prior run, or None."""
    for dir in sorted(reports_dir.glob("partials-*/"), reverse=True):
        if not all((dir / f"{r}.partial.md").exists() for r in reviewers):
            continue
        stored_hash = ""
        sh = dir / "diff.sha256"
        if sh.exists():
            stored_hash = sh.read_text(encoding="utf-8").strip()
        if current_hash and stored_hash != current_hash:
            log(f"Skipping {dir.name} — diff hash mismatch (stale partials)")
            continue
        stored_profile = ""
        pf = dir / "profile.txt"
        if pf.exists():
            stored_profile = pf.read_text(encoding="utf-8").strip()
        if current_profile and stored_profile != current_profile:
            log(f"Skipping {dir.name} — profile mismatch "
                f"(was '{stored_profile}', now '{current_profile}')")
            continue
        return dir
    return None


# --- input snapshot (Phase 1.6) ----------------------------------------------

def _write_inputs_snapshot(partials_dir: Path, *, diff_hash: str, spec_path: Path) -> None:
    """Write inputs.json to partials_dir for reproducibility tracking.

    Two runs with identical inputs.json should produce identical findings.json
    (modulo LLM noise — but the *set* of findings should be stable).

    Fields per Phase 1.6:
    - diff_sha256
    - spec_sha256
    - claude_md_sha256 (per loaded CLAUDE.md)
    - severity_rubric_sha256
    - manifest_sha256
    - model (from config/models.yml role=review-internal)
    - framework_git_sha
    """
    inputs = {"diff_sha256": diff_hash}

    if spec_path.exists():
        inputs["spec_sha256"] = _sha256_of(spec_path)
    else:
        inputs["spec_sha256"] = ""

    # CLAUDE.md files: gather all that went into claude-md-context.md
    ctx_file = partials_dir.parent / "pending-*" / "claude-md-context.md"
    pending_dirs = sorted(partials_dir.parent.glob("pending-*"))
    if pending_dirs:
        ctx_candidate = pending_dirs[-1] / "claude-md-context.md"
        if ctx_candidate.exists():
            inputs["context_sha256"] = _sha256_of(ctx_candidate)
        else:
            inputs["context_sha256"] = ""
    else:
        inputs["context_sha256"] = ""

    # severity rubric
    rubric = FRAMEWORK_ROOT / "config" / "severity-rubric.md"
    if rubric.exists():
        inputs["severity_rubric_sha256"] = _sha256_of(rubric)
    else:
        inputs["severity_rubric_sha256"] = ""

    # profile manifest (active profile)
    manifest_path = None
    profile_name = _resolve_profile_field("name") or "generic"
    for candidate in [FRAMEWORK_ROOT / "profiles" / profile_name / "manifest.yml"]:
        if candidate.exists():
            manifest_path = candidate
            break
    if manifest_path:
        inputs["manifest_sha256"] = _sha256_of(manifest_path)
    else:
        inputs["manifest_sha256"] = ""

    # model (from config/models.yml role=review-internal)
    # Placeholder: scripts/review-runner.py loads this; for now record "unknown"
    inputs["model"] = os.environ.get("KLC_REVIEW_MODEL", "unknown")

    # framework git sha
    try:
        r = subprocess.run(
            ["git", "-C", str(FRAMEWORK_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            inputs["framework_git_sha"] = r.stdout.strip()
        else:
            inputs["framework_git_sha"] = ""
    except (OSError, subprocess.TimeoutExpired):
        inputs["framework_git_sha"] = ""

    (partials_dir / "inputs.json").write_text(
        json.dumps(inputs, indent=2) + "\n", encoding="utf-8",
    )


def _should_run_external(*,
                         no_external: bool,
                         reviewers_cfg: dict,
                         meta: dict) -> bool:
    """Return True iff the external reviewer should run for this ticket.

    KLC-120 D-010: a thin wrapper over `review_plan.external_gate`, which
    owns the rule (--no-external, meta.review.skip_external, enabled,
    min_track, then a provider-aware key/CLI check, AC-10). The keyword
    signature and bool return stay unchanged so every existing caller —
    the six tests in test_review_external_default.py and
    scripts/review.py's own call — is untouched; the skip reason is
    logged here but read by tests directly from `external_gate`.
    """
    import review_plan
    run, reason = review_plan.external_gate(
        no_external=no_external, ext_cfg=reviewers_cfg, meta=meta)
    if not run and reason:
        log(f"external reviewer: {reason} — skipping")
    return run


def _plan_passes(*, always: list[dict], conditional_results: list[tuple[str, bool, str]],
                 cascade_decision, route: dict, want_external: bool,
                 ext_reason: str | None, meta_track: str, ticket_meta: dict,
                 plan_path: str) -> list[dict]:
    """KLC-120 AC-1: enumerate every review pass this ticket's track WOULD
    run, independent of which of them THIS invocation actually dispatches.
    `plan_path` is "client" for the in-client (--plan-only) path and
    "headless" for scripts/review.py's own auto-dispatch/manual-job-card
    path — see design/options.md's pass-enumeration table."""
    import review_plan
    passes: list[dict] = []
    cheap = cascade_decision is not None and not cascade_decision.use_full_review

    # manifest-always (security, architecture, performance, test-coverage)
    for r in always:
        name = r["name"]
        if plan_path == "client":
            passes.append(review_plan.pass_entry(
                name, "manifest-always", "manifest", None, None, "skipped",
                skip_reason=review_plan.PROFILE_SKIP))
        elif cheap:
            passes.append(review_plan.pass_entry(
                name, "manifest-always", "manifest", None, None, "skipped",
                skip_reason=f"cascade chose the cheap path: {cascade_decision.reason}"))
        else:
            passes.append(review_plan.pass_entry(
                name, "manifest-always", "manifest", None, None, "planned"))

    # manifest-conditional (deep-impact and any profile that adds more)
    for name, fired, selected_by in conditional_results:
        if cheap and plan_path != "client":
            passes.append(review_plan.pass_entry(
                name, "manifest-conditional", selected_by, None, None, "skipped",
                skip_reason=f"cascade chose the cheap path: {cascade_decision.reason}"))
        elif fired:
            passes.append(review_plan.pass_entry(
                name, "manifest-conditional", selected_by, None, None, "planned"))
        else:
            passes.append(review_plan.pass_entry(
                name, "manifest-conditional", selected_by, None, None, "skipped",
                skip_reason=selected_by))

    # cascade-cheap (the single Sonnet reviewer the cascade substitutes)
    if cheap and plan_path != "client":
        passes.append(review_plan.pass_entry(
            "cheap", "cascade-cheap", cascade_decision.reason, None, None, "planned"))

    # independent passes: the mandatory fresh code-reviewer and the drift
    # reviewer. scripts/review.py never dispatches either (F-017/Non-goals);
    # they exist only on the in-client path.
    if plan_path == "client":
        passes.append(review_plan.pass_entry(
            "code-review", "independent", "CLAUDE.md mandatory fresh reviewer",
            None, None, "planned"))
        try:
            import spec_review
            signals = {
                "risk_tags": ticket_meta.get("risk_tags") or [],
                "scope_expansion": bool(ticket_meta.get("scope_expansion")),
                "sentinel_hits": bool(ticket_meta.get("sentinel_hits")),
            }
            drift_run = spec_review.should_run(meta_track, signals)
            drift_reason = "spec_review.should_run"
        except Exception as exc:
            drift_run, drift_reason = True, f"spec_review unreadable ({exc})"
        if drift_run:
            passes.append(review_plan.pass_entry(
                "drift", "independent", drift_reason, None, None, "planned"))
        else:
            passes.append(review_plan.pass_entry(
                "drift", "independent", drift_reason, None, None, "skipped",
                skip_reason="spec_review.should_run is False for this track"))
    else:
        passes.append(review_plan.pass_entry(
            "code-review", "independent", "n/a", None, None, "skipped",
            skip_reason=review_plan.CLIENT_ONLY))
        passes.append(review_plan.pass_entry(
            "drift", "independent", "n/a", None, None, "skipped",
            skip_reason=review_plan.CLIENT_ONLY))

    # external
    if want_external:
        passes.append(review_plan.pass_entry(
            "external", "external", "external_gate", route.get("provider"),
            route.get("model"), "planned"))
    else:
        passes.append(review_plan.pass_entry(
            "external", "external", "external_gate", route.get("provider"),
            route.get("model"), "skipped",
            skip_reason=ext_reason or "unspecified"))

    return passes


# --- KLC-127 AC-14/AC-22: the pooled, cross-reviewer JSON findings ----------

def _pooled_findings(partials_dir: Path, ticket_key: str | None) -> tuple[list, list[str]]:
    """The JSON-partial pipeline: validate each reviewer's `findings.json`
    with `handback.validate_findings("code-review", ...)`, stamp `reviewer`
    (the partial directory name) and `kind` ("code-review"), dedupe
    cross-reviewer duplicates, and sort for the report — `aggregate`, then
    `dedupe`, then `sort_for_report`, in that order (AC-22, F-001's gap:
    these three were imported and never called). Writes
    `review/headless-findings.json` (D-111) when *ticket_key* is known.
    Returns `(pooled, notes)` — an invalid partial is left OUT with one note
    naming the reviewer and its errors, never a crash."""
    notes: list[str] = []
    raw = aggregate(partials_dir, notes=notes, kind="code-review",
                    validate=lambda items: handback.validate_findings("code-review", items))
    pooled = sort_for_report(dedupe(raw))
    if ticket_key:
        handback.write_headless_findings(ticket_key, raw)
    return pooled, notes


def _issue_buckets(reviewers_data: dict, pooled: list,
                   diff_scope: dict) -> tuple[str, str, str]:
    """Render the blocking / non-blocking / out-of-scope markdown lines from
    the POOLED (deduped) JSON findings, plus any legacy markdown-only issues
    — a reviewer whose partial carries no `findings.json` at all keeps
    rendering through `reviewers_data` exactly as before (unaffected by the
    JSON pooling)."""
    blocking: list[str] = []
    non_blocking: list[str] = []
    out_of_scope: list[str] = []

    for f in pooled:
        title = f"{f.title} — {f.file}:{f.line}"
        if _classify_scope(diff_scope, f"{f.file}:{f.line}") is False:
            if f.severity != "INFO":
                out_of_scope.append(f"- [{f.severity}] {title}")
            continue
        line = f"- [{f.severity}] {title}"
        (blocking if f.severity in ("CRITICAL", "HIGH") else non_blocking).append(line)

    for r in reviewers_data.values():
        for i in r["issues"]:
            if "finding" in i:
                continue  # a JSON-sourced issue: already rendered from `pooled` above
            if i.get("suspect_out_of_scope"):
                if i["severity"] != "INFO":
                    out_of_scope.append(f"- [{i['severity']}] {i['title']}")
                continue
            is_block = i["severity"] in ("CRITICAL", "HIGH")
            (blocking if is_block else non_blocking).append(f"- [{i['severity']}] {i['title']}")

    def _render(lines: list[str]) -> str:
        return "\n".join(lines) if lines else "_None._"

    return _render(blocking), _render(non_blocking), _render(out_of_scope)


# --- main --------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="review",
                                 description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diff", required=True,
                    help="Unified diff file OR a git ref (HEAD, main...feat, ...).")
    ap.add_argument("--spec", required=True, type=Path,
                    help="Path to the ticket spec.")
    ap.add_argument("--external", action="store_true",
                    help="Also run the external reviewer (legacy flag; default-on for S+ now).")
    ap.add_argument("--no-external", dest="no_external", action="store_true",
                    help="Skip the external reviewer even when default-on in reviewers.yml.")
    ap.add_argument("--plan-only", dest="plan_only", action="store_true",
                    help="KLC-120: write .klc/tickets/<KEY>/review-plan.json for the "
                         "in-client path and exit — no job card, no dispatch.")
    ap.add_argument("--over-cap", dest="over_cap", action="store_true",
                    help="KLC-120: dispatch even when the review plan has more than "
                         "review.max_llm_passes for this track. Records cap_override "
                         "in the report frontmatter.")
    args = ap.parse_args(argv)

    if not args.spec.is_file():
        return die(f"spec file not found: {args.spec}")

    root = project_root()
    reports_dir = klc_reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)

    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d-%H-%M")
    pending_dir  = reports_dir / f"pending-{ts}"
    partials_dir = reports_dir / f"partials-{ts}"
    pending_dir.mkdir(parents=True, exist_ok=True)
    partials_dir.mkdir(parents=True, exist_ok=True)

    # 0. Retention.
    _prune_reports(
        reports_dir,
        partials_days=int(os.environ.get("RETENTION_PARTIALS_DAYS", "7")),
        runs=int(os.environ.get("RETENTION_RUNS", "30")),
    )

    # 1. Resolve --diff.
    diff_file = pending_dir / "diff.patch"
    if not _resolve_diff(args.diff, diff_file):
        return die(f"--diff is neither a file nor a resolvable git ref: {args.diff}")
    try:
        diff_lines = sum(1 for _ in diff_file.open("rb"))
    except OSError:
        diff_lines = 0
    log(f"Diff: {diff_file} ({diff_lines} lines)")

    current_hash = _sha256_of(diff_file)
    (partials_dir / "diff.sha256").write_text(current_hash + "\n", encoding="utf-8")

    current_profile = _resolve_profile_field("name") or "unknown"
    (partials_dir / "profile.txt").write_text(current_profile + "\n", encoding="utf-8")

    # Phase 1.6: snapshot inputs for reproducibility check
    _write_inputs_snapshot(partials_dir, diff_hash=current_hash, spec_path=args.spec)

    # 2. CLAUDE.md context.
    ctx_file = pending_dir / "claude-md-context.md"
    modules_json = klc_dir() / "index" / "modules.json"
    modules_idx = _modules_index(modules_json)
    affected = _affected_modules(diff_file, modules_json) if modules_json.exists() else []
    (pending_dir / "affected-modules.txt").write_text(
        "\n".join(affected) + ("\n" if affected else ""), encoding="utf-8",
    )
    _write_ctx_bundle(ctx_file, root=root, modules_idx=modules_idx, affected=affected)
    log(f"Context bundle: {ctx_file}")

    # Phase 2.3: collect ADRs and test-plan if available
    adr_paths, adr_inlined = _collect_adrs(root, modules_idx, affected)
    adr_context_file: Path | None = None
    if adr_inlined:
        adr_context_file = pending_dir / "adr-context.md"
        adr_chunks = []
        for path, content in adr_inlined.items():
            adr_chunks.append(f"<!-- BEGIN ADR: {path} -->")
            adr_chunks.append(content.rstrip("\n"))
            adr_chunks.append(f"<!-- END ADR: {path} -->")
        adr_context_file.write_text("\n".join(adr_chunks) + "\n", encoding="utf-8")
        log(f"ADR context: {adr_context_file} ({len(adr_inlined)} ADRs)")

    test_plan_file: Path | None = None
    if args.spec.parent.name.startswith("PROJ-") or args.spec.parent.name.startswith("TICK-"):
        candidate = args.spec.parent / "test-plan.md"
        if candidate.exists():
            test_plan_file = candidate
            log(f"Test plan: {test_plan_file}")

    # 3. Reviewer discovery + job cards.
    always, conditional = _load_reviewers()
    diff_text = diff_file.read_text(encoding="utf-8", errors="ignore")
    meta_track = _read_ticket_meta(args.spec).get("track", "")
    active: list[dict] = list(always)
    conditional_results: list[tuple[str, bool, str]] = []   # KLC-120 AC-1
    for r in conditional:
        # Validate legacy regex if present (still required for backward compat)
        trig = r.get("trigger", "")
        if trig and not _validate_regex(trig):
            return die(f"reviewer '{r['name']}': bad trigger regex: {trig}")
        try:
            # KLC-120 review-fix MEDIUM: distinguish the track gate from a
            # pattern that simply didn't match, so the plan's skip reason
            # is honest about WHY (_evaluate_conditional_trigger only
            # returns a bool — its own callers, e.g.
            # test_deep_impact_trigger.py, depend on that shape, so the
            # gate is re-checked here rather than changed there).
            allowed_tracks = r.get("enabled_for_tracks")
            if allowed_tracks is not None and meta_track not in allowed_tracks:
                fired = False
                selected_by = f"track {meta_track} not in enabled_for_tracks"
            else:
                fired = _evaluate_conditional_trigger(r, diff_text, meta_track, modules_json)
                selected_by = "trigger fired" if fired else "no trigger fired"
        except Exception as exc:
            # C-004: fail toward PLANNING the pass, never toward treating an
            # unevaluable trigger as "no risk".
            fired = True
            selected_by = f"trigger could not be evaluated: {exc}"
        if fired:
            active.append(r)
        elif not args.plan_only:
            _write_skip_partial(partials_dir / f"{r['name']}.partial.md",
                                r["name"])
        conditional_results.append((r["name"], fired, selected_by))

    # 3a. Cascade routing: check if peripheral diff qualifies for cheap review.
    ticket_key = args.spec.parent.name if args.spec.parent.name.startswith("KLC-") else None
    cascade_decision = None
    try:
        sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
        import review_cascade as _rc
        from _yaml import parse as _yml_parse
        reviewers_cfg_path = FRAMEWORK_ROOT / "config" / "reviewers.yml"
        reviewers_cfg = _yml_parse(reviewers_cfg_path.read_text()) if reviewers_cfg_path.exists() else {}
        cascade_cfg = reviewers_cfg.get("cascade") or {}
        if cascade_cfg.get("enabled", False) and ticket_key:
            cascade_decision = _rc.decide(ticket_key, diff_file)
            if not cascade_decision.use_full_review:
                log(f"Cascade: cheap review ({cascade_decision.reason})")
                cheap_path = FRAMEWORK_ROOT / "core" / "agents" / "review" / "cheap.md"
                active = [{"name": "cheap", "path": str(cheap_path.relative_to(FRAMEWORK_ROOT)),
                           "filter": ""}]
            else:
                log(f"Cascade: full review ({cascade_decision.reason})")
    except Exception as _cascade_err:
        log(f"Cascade check failed ({_cascade_err}); proceeding with full review")

    reviewers_names = [r["name"] for r in active]

    # KLC-120 AC-1/AC-2/AC-9/F-022: build and write the review plan BEFORE
    # any job card exists. The external decision moves up to here (it used
    # to be computed only after every internal partial already existed,
    # scripts/review.py:1213's old early return) so the plan can count and
    # name the external pass on the very first invocation.
    import review_plan
    plan_path = "client" if args.plan_only else "headless"
    ticket_meta: dict = {}
    if ticket_key:
        try:
            meta_path = klc_dir() / "tickets" / ticket_key / "meta.json"
            if meta_path.exists():
                ticket_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    reviewers_cfg, cfg_note = review_plan.load_reviewers_cfg()
    ext_cfg = reviewers_cfg.get("external_reviewer") or {}
    route = review_plan.external_route(ext_cfg, meta_track)
    run_ext, ext_reason = review_plan.external_gate(
        no_external=getattr(args, "no_external", False),
        ext_cfg=ext_cfg, meta=ticket_meta, route=route)
    want_external = args.external or run_ext
    passes = _plan_passes(
        always=always, conditional_results=conditional_results,
        cascade_decision=cascade_decision, route=route,
        want_external=want_external, ext_reason=ext_reason,
        meta_track=meta_track, ticket_meta=ticket_meta, plan_path=plan_path)
    plan = review_plan.build_plan(
        ticket=ticket_key, track=meta_track, path=plan_path,
        diff_sha256=current_hash,
        cap=review_plan.cap_for(meta_track, reviewers_cfg),
        override=args.over_cap, passes=passes,
        cascade=cascade_decision.as_dict() if cascade_decision else None,
        notes=[n for n in (cfg_note, route.get("note")) if n])
    if ticket_key:
        # KLC-127 AC-29: re-planning the same diff must never reset an
        # already-executed pass back to `planned` (it would let a later
        # `handback.py take` record the same pass twice).
        old_plan = None
        try:
            old_path = klc_dir() / "tickets" / ticket_key / "review-plan.json"
            old_plan = json.loads(old_path.read_text(encoding="utf-8")) if old_path.is_file() else None
        except (OSError, json.JSONDecodeError):
            old_plan = None
        plan = review_plan.carry_forward(plan, old_plan)
        review_plan.write_plan(ticket_key, plan)
    for line in review_plan.plan_lines(plan):
        log(line)

    # KLC-120 AC-5/AC-6: enforce the cap right after the plan is printed,
    # before any job card, on either path. Skipped passes never count
    # toward the cap (D-005); over the cap the run refuses WHOLE — it
    # never trims the plan to fit (D-012).
    cap = plan["cap"]
    planned_count = review_plan.counted(plan)
    if cap is not None and planned_count > cap and not args.over_cap:
        return die(
            f"review plan has {planned_count} passes, over the {meta_track} "
            f"cap of {cap} (review.max_llm_passes); nothing was dispatched. "
            "Re-run with --over-cap to proceed.", code=2)
    cap_override = bool(cap is not None and planned_count > cap)

    if args.plan_only:
        return 0

    allowlist_live = klc_knowledge_dir() / "reviewer-allowlist.yml"
    allowlist_seed = FRAMEWORK_ROOT / "config" / "reviewer-allowlist.seed.yml"
    allowlist = allowlist_live if allowlist_live.exists() else allowlist_seed

    # Phase 4.6: build call graph slice for changed files
    callgraph_slice_file = _build_callgraph_slice(diff_file, pending_dir)
    if callgraph_slice_file:
        log(f"Call graph slice: {callgraph_slice_file}")

    for r in active:
        name = r["name"]
        filter_pat = r.get("filter") or ""
        if filter_pat:
            trimmed = pending_dir / f"diff-{name}.patch"
            if _filter_diff(diff_file, filter_pat, trimmed):
                reviewer_diff = trimmed
            else:
                reviewer_diff = diff_file
        else:
            reviewer_diff = diff_file

        reviewer_ctx: Path = ctx_file
        if filter_pat and modules_json.exists():
            reviewer_affected = _affected_modules(reviewer_diff, modules_json)
            trimmed_ctx = pending_dir / f"ctx-{name}.md"
            _write_reviewer_ctx(
                trimmed_ctx,
                root_claude=root / "CLAUDE.md",
                modules_idx=modules_idx,
                affected=reviewer_affected,
                project_root_dir=root,
            )
            reviewer_ctx = trimmed_ctx

        # Phase 1.4: load severity rubric + extract rule catalog from prompt
        severity_rubric_path = FRAMEWORK_ROOT / "config" / "severity-rubric.md"
        prompt_path = FRAMEWORK_ROOT / r["path"]
        rule_catalog_text = _extract_rules_catalog(prompt_path)

        _write_job_card(
            pending_dir / f"job-{name}.md",
            reviewer=name,
            prompt=r["path"],
            diff=reviewer_diff,
            spec=args.spec,
            context=reviewer_ctx,
            allowlist=allowlist,
            severity_rubric=severity_rubric_path,
            rule_catalog_content=rule_catalog_text,
            adr_context=adr_context_file,
            test_plan=test_plan_file,
            callgraph_slice=callgraph_slice_file,
            partial=partials_dir / f"{name}.partial.md",
        )

    log(f"Job cards: {pending_dir}")

    # 4. Optional parallel dispatch.
    run_local = os.environ.get("RUN_LOCAL_SUBAGENTS") == "1"
    review_runner = os.environ.get("REVIEW_RUNNER")
    if run_local and review_runner:
        runner_path = Path(review_runner)
        if not runner_path.is_file():
            return die(f"REVIEW_RUNNER not a file: {review_runner}")
        log("Spawning local sub-agent runner for each job card")
        def _fire(name: str) -> int:
            argv = [sys.executable if runner_path.suffix == ".py" else str(runner_path)]
            if runner_path.suffix == ".py":
                argv.append(str(runner_path))
            argv.extend([
                str(pending_dir / f"job-{name}.md"),
                str(partials_dir / f"{name}.partial.md"),
            ])
            r = subprocess.run(argv)
            return r.returncode
        with ThreadPoolExecutor(max_workers=max(1, len(reviewers_names))) as ex:
            futures = {ex.submit(_fire, n): n for n in reviewers_names}
            for fut in as_completed(futures):
                # ignore individual rc; synthetic CRITICAL handles aggregation
                fut.result()
    else:
        print("")
        print("--- ACTION REQUIRED ---------------------------------------------")
        print("Review sub-agents must now be run. Open Claude Code and, for each")
        print(f"card in {pending_dir}, execute the prompt and save the output to")
        print("the 'Write the sub-agent's output to' path.")
        print("")
        print("Job cards:")
        for name in reviewers_names:
            print(f"  {pending_dir / f'job-{name}.md'}")
        print("")
        print("When all partials exist, re-run:")
        print(f"  {Path(sys.argv[0]).resolve()} --diff '{args.diff}' "
              f"--spec '{args.spec}'"
              + (" --external" if args.external else "")
              + (" --over-cap" if args.over_cap else ""))
        print("-----------------------------------------------------------------")

    missing = [n for n in reviewers_names
               if not (partials_dir / f"{n}.partial.md").exists()]

    # 4b. Partial reuse.
    if missing:
        reuse = _try_reuse_partials(
            reports_dir,
            reviewers=reviewers_names,
            current_hash=current_hash,
            current_profile=current_profile,
        )
        if reuse is not None:
            log(f"Reusing partials from {reuse}")
            partials_dir = reuse
            missing = []

    if missing:
        # Still incomplete: return 0 and wait for re-entry.
        return 0

    # 5. Optional external reviewer (default-on for S+ per reviewers.yml).
    # KLC-120: the decision (ticket_meta, ext_cfg, route, want_external) was
    # already computed above the plan, before any job card — reused here
    # unchanged so the plan and the card always agree.
    ext_card: Path | None = None
    ext_out: Path | None = None
    if want_external:
        ext_card = pending_dir / "job-external.md"
        ext_out  = partials_dir / "external.json"
        ext_card.write_text(
            "# External review job\n\n"
            f"Prompt:  core/agents/external-review.md\n"
            f"Provider: {route.get('provider')}\n"
            f"Model:    {route.get('model')}\n"
            "Inputs:\n"
            f"- diff:              {diff_file}\n"
            f"- spec:              {args.spec}\n"
            f"- claude_md_context: {ctx_file}\n"
            "\n"
            "The agent must print a JSON summary (see external-review.md) and\n"
            "write the full provider-markdown report to the location configured\n"
            "in config/reviewers.yml (report_path). Save the JSON summary to:\n"
            f"  {ext_out}\n",
            encoding="utf-8",
        )

    # 6. Tier classification + sentinel scan (Phase 3a).
    tier_classification: dict = {}
    sentinel_matches: dict = {}
    try:
        # Classify files by risk tier
        classify_script = FRAMEWORK_ROOT / "core" / "skills" / "classify_tier.py"
        r = subprocess.run(
            [sys.executable, str(classify_script), "--diff", str(diff_file), "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            tier_classification = json.loads(r.stdout)
        # Scan for sentinel patterns
        sentinel_script = FRAMEWORK_ROOT / "core" / "skills" / "scan_sentinels.py"
        r = subprocess.run(
            [sys.executable, str(sentinel_script), "--diff", str(diff_file), "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            sentinel_matches = json.loads(r.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        log(f"Tier/sentinel scan failed: {e}")

    # 7. Aggregate + render.
    diff_scope = _parse_diff_scope(diff_file)
    reviewers_data: dict[str, dict] = {}
    for p in sorted(partials_dir.glob("*.partial.md")):
        key = p.name[: -len(".partial.md")]
        reviewers_data[key] = _parse_partial(p, diff_scope)

    # KLC-120 AC-3/AC-7/D-015: executed = the pass's partial exists and is
    # neither a skip partial nor a runner-failure partial; the external
    # pass counts as executed when its JSON summary exists. Rewriting the
    # plan here keeps review-plan.json and the rendered report in
    # agreement about what actually ran.
    executed_names = [
        k for k, v in reviewers_data.items()
        if not _is_skip_partial(v)
        and not _is_failed_partial(partials_dir / f"{k}.partial.md")
    ]
    if ext_out and ext_out.exists():
        executed_names.append("external")
    review_plan.mark_executed(plan, executed_names)
    if ticket_key:
        review_plan.write_plan(ticket_key, plan)
    planned_passes = review_plan.counted(plan)
    executed_passes = sum(1 for p in plan["passes"] if p["status"] == "executed")
    skipped_passes = [
        {"reviewer": p["reviewer"], "skip_reason": p.get("skip_reason", "unspecified")}
        for p in plan["passes"] if p["status"] == "skipped"
    ]

    external_block = None
    if ext_out and ext_out.exists():
        try:
            ext_raw = json.loads(ext_out.read_text(encoding="utf-8"))
            external_block = {
                "model":    ext_raw.get("model", "?"),
                "total":    ext_raw.get("total", 0),
                "blocking": ext_raw.get("blocking", 0),
                "notes":    ext_raw.get("notes", ""),
                "path":     ext_raw.get("path", ""),
            }
        except (OSError, json.JSONDecodeError) as e:
            sys.stderr.write(f"review: external summary unparseable: {e}\n")

    # KLC-127 AC-22: the JSON-sourced findings are pooled (aggregate, then
    # dedupe, then sort_for_report, in that order) so one defect reported by
    # several headless reviewers renders once, not once per reviewer
    # (F-001's gap — the three functions were imported and never called).
    # Legacy markdown-only issues (a reviewer with no findings.json at all)
    # keep rendering through `reviewers_data` unchanged.
    pooled_findings, pool_notes = _pooled_findings(partials_dir, ticket_key)
    for _note in pool_notes:
        log(f"headless findings: {_note}")
    blocking_issues, non_blocking_issues, out_of_scope_issues = _issue_buckets(
        reviewers_data, pooled_findings, diff_scope)

    # Phase 3a: tier-aware blocking threshold
    # Build file → tier map
    file_tier_map = {f["path"]: f["tier"] for f in tier_classification.get("files", [])}

    # Load tier thresholds from config
    tier_thresholds = {"critical": "LOW", "core": "HIGH", "peripheral": "CRITICAL"}
    try:
        from _yaml import load_yaml
        tiers_cfg = load_yaml(FRAMEWORK_ROOT / "config" / "tiers.yml")
        for tier_name in ("critical", "core", "peripheral"):
            t = tiers_cfg.get("tiers", {}).get(tier_name, {})
            threshold = t.get("blocking_threshold")
            if threshold:
                tier_thresholds[tier_name] = threshold
    except Exception:
        pass  # use defaults

    # Severity order for threshold comparison
    sev_order = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

    def _is_blocking(issue: dict) -> bool:
        """Check if issue blocks based on its file's tier threshold."""
        # Always block sentinel matches
        if issue.get("is_sentinel"):
            return True
        if issue.get("suspect_out_of_scope"):
            return False
        # Determine threshold from file's tier
        file = issue.get("file", "")
        tier = file_tier_map.get(file, "peripheral")
        threshold_sev = tier_thresholds.get(tier, "CRITICAL")
        issue_sev = issue.get("severity", "INFO")
        return sev_order.get(issue_sev, 0) >= sev_order.get(threshold_sev, 4)

    # Inject sentinel findings as synthetic CRITICAL issues
    if sentinel_matches.get("matches"):
        sentinel_issues = []
        for m in sentinel_matches["matches"]:
            sentinel_issues.append({
                "severity": m.get("severity_override", "CRITICAL"),
                "file": m["file"],
                "line": m["line"],
                "title": f"Sentinel: {m['sentinel_id']} — {m['description']}",
                "body": f"Matched: `{m['matched_text']}`\n\nThis pattern is a high-risk sentinel (config/sentinels.yml).",
                "is_sentinel": True,
                "suspect_out_of_scope": False,
            })
        # Add to a synthetic "sentinels" reviewer
        if "sentinels" not in reviewers_data:
            reviewers_data["sentinels"] = {
                "total": 0,
                "blocking": 0,
                "issues": [],
            }
        reviewers_data["sentinels"]["issues"].extend(sentinel_issues)
        reviewers_data["sentinels"]["total"] += len(sentinel_issues)
        reviewers_data["sentinels"]["blocking"] += len(sentinel_issues)

    # Build reviewer_rows after sentinel injection
    reviewer_rows = [
        {
            "key":      k,
            "label":    _reviewer_label(k),
            "total":    reviewers_data[k]["total"],
            "blocking": reviewers_data[k]["blocking"],
            "skipped":  _is_skip_partial(reviewers_data[k]),
        }
        for k in reviewers_data
    ]

    in_scope_blocking = sum(
        1
        for r in reviewers_data.values()
        for i in r["issues"]
        if _is_blocking(i)
    )
    total_blocking = in_scope_blocking + (external_block["blocking"] if external_block else 0)
    verdict = "APPROVED" if total_blocking == 0 else "CHANGES REQUESTED"

    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError:
        return die("jinja2 required (pip install jinja2)", code=3)

    env = Environment(
        loader=FileSystemLoader(str(FRAMEWORK_ROOT / "core" / "templates")),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("review-report.md.j2")
    final_path = reports_dir / f"review-{ts}.md"
    final_path.write_text(tpl.render(
        timestamp=_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        spec_path=str(args.spec),
        reviewers=reviewer_rows,
        external=external_block,
        blocking_issues=blocking_issues,
        non_blocking_issues=non_blocking_issues,
        out_of_scope_issues=out_of_scope_issues,
        verdict=verdict,
        adrs=[str(p) for p in adr_paths] if adr_paths else [],
        tier_classification=tier_classification,
        sentinel_matches=sentinel_matches,
        planned_passes=planned_passes,
        executed_passes=executed_passes,
        skipped_passes=skipped_passes,
        cap=cap,
        cap_override=cap_override,
    ), encoding="utf-8")

    print(f"REPORT {final_path}")
    print(f"VERDICT {verdict}")
    return 0 if verdict == "APPROVED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
