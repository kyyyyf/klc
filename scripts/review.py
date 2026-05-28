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
        shutil.copy2(p, out_path)
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


# --- reviewer discovery ------------------------------------------------------

def _load_reviewers() -> tuple[list[dict], list[dict]]:
    """Return (always[], conditional[]) from the profile manifest.
    Each entry: {name, path, trigger?, filter?}."""
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
            out.append(entry)
        return out

    return _flatten(data.get("always"), False), _flatten(data.get("conditional"), True)


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
                    partial: Path) -> None:
    # Phase 1.4: write rule_catalog to a temp file next to the card
    rule_catalog_path = card.parent / f"rule_catalog-{reviewer}.txt"
    rule_catalog_path.write_text(rule_catalog_content, encoding="utf-8")

    # Phase 2.3: optional ADR and test-plan context
    adr_line = f"- adr_context:       {adr_context}\n" if adr_context else ""
    test_plan_line = f"- test_plan:         {test_plan}\n" if test_plan else ""

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
    try:
        with findings_json_path.open("r", encoding="utf-8") as f:
            findings_data = json.load(f)
        findings_list = [Finding.from_dict(d) for d in findings_data]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        sys.stderr.write(f"review: {findings_json_path.name}: malformed JSON: {e}\n")
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
                    help="Also run the external reviewer.")
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
    active: list[dict] = list(always)
    for r in conditional:
        trig = r.get("trigger", "")
        if trig and not _validate_regex(trig):
            return die(f"reviewer '{r['name']}': bad trigger regex: {trig}")
        if not trig or _grep_match(trig, diff_text):
            active.append(r)
        else:
            _write_skip_partial(partials_dir / f"{r['name']}.partial.md",
                                r["name"])

    reviewers_names = [r["name"] for r in active]

    allowlist_live = klc_knowledge_dir() / "reviewer-allowlist.yml"
    allowlist_seed = FRAMEWORK_ROOT / "config" / "reviewer-allowlist.seed.yml"
    allowlist = allowlist_live if allowlist_live.exists() else allowlist_seed

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
              + (" --external" if args.external else ""))
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

    # 5. Optional external reviewer.
    ext_card: Path | None = None
    ext_out: Path | None = None
    want_external = args.external
    if not want_external:
        # Honour the framework config toggle too.
        rv_cfg = FRAMEWORK_ROOT / "config" / "reviewers.yml"
        if rv_cfg.exists():
            text = rv_cfg.read_text(encoding="utf-8")
            if re.search(r"^\s*enabled:\s*true", text, re.MULTILINE):
                want_external = True
    if want_external:
        ext_card = pending_dir / "job-external.md"
        ext_out  = partials_dir / "external.json"
        ext_card.write_text(
            "# External review job\n\n"
            f"Prompt:  core/agents/external-review.md\n"
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

    # 6. Aggregate + render.
    diff_scope = _parse_diff_scope(diff_file)
    reviewers_data: dict[str, dict] = {}
    for p in sorted(partials_dir.glob("*.partial.md")):
        key = p.name[: -len(".partial.md")]
        reviewers_data[key] = _parse_partial(p, diff_scope)

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

    def _bucket(blocking: bool) -> str:
        lines: list[str] = []
        for r in reviewers_data.values():
            for i in r["issues"]:
                if i.get("suspect_out_of_scope"):
                    continue
                is_block = i["severity"] in ("CRITICAL", "HIGH")
                if blocking == is_block:
                    lines.append(f"- [{i['severity']}] {i['title']}")
        return "\n".join(lines) if lines else "_None._"

    def _bucket_oos() -> str:
        lines: list[str] = []
        for r in reviewers_data.values():
            for i in r["issues"]:
                if not i.get("suspect_out_of_scope"):
                    continue
                if i["severity"] == "INFO":
                    continue
                lines.append(f"- [{i['severity']}] {i['title']}")
        return "\n".join(lines) if lines else "_None._"

    blocking_issues     = _bucket(True)
    non_blocking_issues = _bucket(False)
    out_of_scope_issues = _bucket_oos()

    in_scope_blocking = sum(
        1
        for r in reviewers_data.values()
        for i in r["issues"]
        if i["severity"] in ("CRITICAL", "HIGH") and not i.get("suspect_out_of_scope")
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
    ), encoding="utf-8")

    print(f"REPORT {final_path}")
    print(f"VERDICT {verdict}")
    return 0 if verdict == "APPROVED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
