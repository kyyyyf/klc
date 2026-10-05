#!/usr/bin/env python3
"""review_map.py — KLC-175 AC-8: the deterministic `## Where to look` list.

Tells the human reviewer which files of a diff deserve the first look, in three
tiers (critical, important, optional), from facts only: the diff, the ticket's
spec / impl-plan / recorded decisions, classify_tier's path -> tier map and git
history. No model call, no network.

Design choices worth knowing:
- Each changed file lands in exactly ONE tier, under the first rule that fires
  (critical rules first), so the list never repeats a file.
- Files no rule picks are left out: the list is a reading order, not an index.
- Every input is optional. A missing impl-plan, ticket dir or git history just
  makes that rule silent, so the result degrades to a shorter list, never an
  exception (a review report must always render).
- `build` takes the reviewers.yml block as `cfg` (`where_to_look.hotspot_min_commits`,
  default 8) plus an optional `repo_root` for `git log`, and the review's
  assessments (`assessments=`): the won't-fix rule fires only for a MEDIUM the
  reviewer chose not to fix, and only when the caller passes them.
- Generated files (klc-plugin, goldens, fixtures) are never critical: a risk-tag
  or a decision that lists one does not outrank the fact that nobody writes it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_signals import TRIGGER_PATTERNS, is_code_file  # noqa: E402

TIERS = ("critical", "important", "optional")
DEFAULT_HOTSPOT_MIN = 8
_MIGRATION = re.compile(r"migrat|schema|\.sql$|alembic", re.IGNORECASE)
_GENERATED = re.compile(r"^klc-plugin/|\.golden$|(^|/)goldens?/|(^|/)fixtures?/")
_WONTFIX = ("wont-fix", "won't-fix", "wontfix")


def _changed_files(diff_text: str) -> list[str]:
    seen: list[str] = []
    for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)", diff_text or "", re.MULTILINE):
        if m.group(2) not in seen:
            seen.append(m.group(2))
    for m in re.finditer(r"^\+\+\+ (?:b/)?(\S+)", diff_text or "", re.MULTILINE):
        if m.group(1) != "/dev/null" and m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def _sections(diff_text: str) -> dict[str, str]:
    """path -> that file's slice of the diff."""
    out: dict[str, str] = {}
    chunks = re.split(r"(?m)^(?=diff --git )", diff_text or "")
    for chunk in chunks:
        m = re.search(r"^\+\+\+ (?:b/)?(\S+)", chunk, re.MULTILINE)
        if m and m.group(1) != "/dev/null":
            out[m.group(1)] = chunk
    return out


def _public_api_line(section: str) -> int | None:
    """New-file line number of the first added line that adds public API, or
    None when there is none."""
    pat = re.compile(TRIGGER_PATTERNS["changed_public_api"])
    new_line = 0
    for ln in section.splitlines():
        h = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", ln)
        if h:
            new_line = int(h.group(1))
            continue
        if ln.startswith("+++") or ln.startswith("---") or new_line == 0:
            continue
        if ln.startswith("+"):
            if pat.search(ln):
                return new_line
            new_line += 1
        elif not ln.startswith("-"):
            new_line += 1
    return None


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _risk_tags(ticket_dir: Path) -> list[str]:
    tags: list[str] = []
    try:
        meta = json.loads(_read(ticket_dir / "meta.json") or "{}")
        raw = meta.get("risk_tags") if isinstance(meta, dict) else None
        if isinstance(raw, list):
            tags += [str(t) for t in raw if str(t).strip()]
    except json.JSONDecodeError:
        pass
    m = re.search(r"^risk_tags:\s*\[(.*?)\]", _read(ticket_dir / "spec.md"), re.MULTILINE)
    if m:
        tags += [t.strip() for t in m.group(1).split(",") if t.strip()]
    return tags


def _plan_steps(ticket_dir: Path) -> list[dict]:
    """impl-plan.md steps: {addresses_ac, has_decision, files}."""
    text = _read(ticket_dir / "impl-plan.md")
    steps = []
    for block in re.split(r"(?m)^(?=## step-)", text):
        if not block.startswith("## step-"):
            continue
        aff = re.search(r"\*\*Affected files:\*\*(.*)", block)
        files = re.findall(r"`([^`]+)`", aff.group(1)) if aff else []
        adr = re.search(r"\*\*Addresses:\*\*(.*)", block)
        steps.append({
            "addresses_ac": bool(adr and re.search(r"AC-\d+", adr.group(1))),
            "has_decision": bool(re.search(r"\[!DECISION\b|^DECISION\b", block, re.MULTILINE)),
            "files": files,
        })
    return steps


def _decision_texts(ticket_dir: Path) -> list[str]:
    try:
        from items import iter_items
        found = iter_items(ticket_dir)
    except Exception:
        return []
    return [" ".join(list(it.attrs.values()) + it.body) for it in found if it.type == "DECISION"]


def _wontfix_medium(assessments) -> dict[str, int | None]:
    """file -> line of each MEDIUM finding assessed won't-fix. *assessments* is
    a list of {file, line, severity, disposition}; None or junk gives {}."""
    out: dict[str, int | None] = {}
    for r in assessments if isinstance(assessments, list) else []:
        if (isinstance(r, dict) and str(r.get("severity", "")).upper() == "MEDIUM"
                and str(r.get("disposition", "")).lower() in _WONTFIX and r.get("file")):
            line = r.get("line")
            out.setdefault(str(r["file"]), line if isinstance(line, int) else None)
    return out


def _layer0_files(tdir: Path) -> set[str]:
    """Files a layer-0 finding of the latest round actually names."""
    try:
        import findings_store
        rows, _ = findings_store.read_dicts(tdir, "layer0")
    except Exception:
        return set()
    if not rows:
        return set()
    top = max(findings_store._round_of(d) for d in rows)
    return {str(d["file"]) for d in rows
            if findings_store._round_of(d) == top and d.get("file") and d["file"] != "-"}


def _names_path(text: str, path: str) -> bool:
    """True when *text* mentions *path* as a whole path, not as the tail or head
    of a longer one (`a.py` is not in `data.py` or `a.pyc`)."""
    return re.search(r"(?<![\w/.\-])" + re.escape(path) + r"(?![\w/\-]|\.\w)", text) is not None


def _churn(repo_root: str | None, files: list[str] | None = None) -> dict[str, int]:
    """Commits touching each of *files* in the last 90 days; {} without usable
    git. The log is limited to the diff's own files (a pathspec), so its cost
    does not grow with the repo's activity."""
    if not files:
        return {}
    counts: dict[str, int] = {}
    for i in range(0, len(files), 200):
        chunk = files[i:i + 200]
        try:
            r = subprocess.run(
                ["git", "log", "--since=90.days", "--name-only", "--pretty=format:",
                 "--", *chunk],
                cwd=repo_root or None, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return {}
        if r.returncode != 0:
            return {}
        for ln in r.stdout.splitlines():
            if ln.strip():
                counts[ln.strip()] = counts.get(ln.strip(), 0) + 1
    return counts


def _entry(path: str, reason: str, line: int | None = None) -> dict:
    return {"file": f"{path}:{line}" if line else path, "reason": reason}


def build(diff_text: str, ticket_dir, cfg, file_tiers, assessments=None) -> dict:
    """The three tiers of `{file, reason}` for *diff_text*. Never raises."""
    tiers: dict[str, list[dict]] = {t: [] for t in TIERS}
    try:
        files = _changed_files(diff_text)
        if not files:
            return tiers
        cfg = cfg if isinstance(cfg, dict) else {}
        file_tiers = file_tiers if isinstance(file_tiers, dict) else {}
        tdir = Path(ticket_dir) if ticket_dir else Path("/nonexistent-ticket-dir")
        wtl = cfg.get("where_to_look") if isinstance(cfg.get("where_to_look"), dict) else {}
        try:
            min_commits = int(wtl.get("hotspot_min_commits", DEFAULT_HOTSPOT_MIN))
        except (TypeError, ValueError):
            min_commits = DEFAULT_HOTSPOT_MIN

        sections = _sections(diff_text)
        decisions = _decision_texts(tdir)
        steps = _plan_steps(tdir)
        risky = bool(_risk_tags(tdir))
        risk_files = {f for s in steps if s["addresses_ac"] for f in s["files"]} if risky else set()
        plan_decision_files = {f for s in steps if s["has_decision"] for f in s["files"]}
        wontfix = _wontfix_medium(assessments)
        gate_files = _layer0_files(tdir)
        churn = _churn(cfg.get("repo_root"), files)

        for f in files:
            if _GENERATED.search(f):                 # never critical: nobody writes it
                tiers["optional"].append(_entry(f, "generated"))
            elif any(_names_path(text, f) for text in decisions) or f.startswith("docs/adr/"):
                tiers["critical"].append(_entry(f, "decision"))
            elif _MIGRATION.search(f):
                tiers["critical"].append(_entry(f, "migration"))
            elif is_code_file(f) and _public_api_line(sections.get(f, "")):
                tiers["critical"].append(_entry(f, "public-api", _public_api_line(sections[f])))
            elif file_tiers.get(f) == "critical":
                tiers["critical"].append(_entry(f, "tier"))
            elif f in risk_files:
                tiers["critical"].append(_entry(f, "risk-tag"))
            elif f in wontfix:
                tiers["important"].append(_entry(f, "wont-fix", wontfix[f]))
            elif f in plan_decision_files:
                tiers["important"].append(_entry(f, "plan-decision"))
            elif f.startswith("core/agents/"):
                tiers["important"].append(_entry(f, "agent-prompt"))
            elif f.startswith(".klc/"):
                tiers["optional"].append(_entry(f, "service"))
            elif churn.get(f, 0) >= min_commits:
                tiers["important"].append(_entry(f, "hotspot"))
            elif f in gate_files:                    # a layer-0 check named this file
                tiers["optional"].append(_entry(f, "gate"))
    except Exception:  # a report must always render
        return {t: [] for t in TIERS}
    return tiers


def render(tiers: dict) -> str:
    """Markdown for the report: `## Where to look` with one `###` per tier."""
    lines = ["## Where to look"]
    for name in TIERS:
        lines.append(f"### {name.capitalize()}")
        entries = (tiers or {}).get(name) or []
        lines += [f"- `{e['file']}` — {e['reason']}" for e in entries] or ["_None._"]
    return "\n".join(lines)
