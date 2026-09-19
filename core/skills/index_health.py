#!/usr/bin/env python3
"""index_health.py — KLC-107: pure diagnostic functions behind `klc doctor`'s
index-freshness, index-views, index-degraded and index-hook checks.

Each function returns ``(messages, severity)`` where ``severity`` is one of
``fail``, ``warn`` or ``pass``. Nothing here writes to disk or raises on a
malformed artifact — a diagnostic that crashes the diagnosis is worse than
one that reports "unparseable".
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))
import index_coverage  # noqa: E402

VIEWS = ("inventory.json", "test_map.json", "file_roles.json",
         "module_edges.json", "symbol_usage.json")


def _uninitialised(index_dir: Path):
    """D-003 / Q-007: no index at all is a different diagnosis from a stale
    one. Gated on `.last-run`, not on the views, so the only state it softens
    is "klc install ran, klc init did not"."""
    if (index_dir / ".last-run").exists():
        return None
    return (["`.klc/index/.last-run` absent — the index was never built; "
             "run `klc init --scan-only`"], "warn")


def _git_head(repo: Path) -> str:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=5)
    return r.stdout.strip() if r.returncode == 0 else ""


def _commit_distance(repo: Path, last: str, head: str) -> int:
    """Symmetric commit distance: counts commits reachable from either side
    but not the other, so HEAD-behind-.last-run reports a distance too."""
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--left-right", "--count",
         f"{last}...{head}"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        return 0
    parts = r.stdout.split()
    try:
        return sum(int(p) for p in parts)
    except ValueError:
        return 0


def freshness(index_dir: Path, repo: Path) -> tuple[list[str], str]:
    pre = _uninitialised(index_dir)
    if pre:
        return pre
    last = (index_dir / ".last-run").read_text(encoding="utf-8").strip()
    head = _git_head(repo)
    if not head:
        return (["git rev-parse HEAD failed — cannot judge index freshness"], "fail")
    if last == head:
        return ([], "pass")
    n = _commit_distance(repo, last, head)   # symmetric: counts either direction
    return ([f"index baseline {last[:8]} != HEAD {head[:8]} "
             f"({n} commit(s) apart) — run `klc update`"], "fail")


def views(index_dir: Path) -> tuple[list[str], str]:
    pre = _uninitialised(index_dir)
    if pre:
        return pre
    bad = []
    for name in VIEWS:
        p = index_dir / name
        if not p.exists():
            bad.append(f"{name}: missing")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            bad.append(f"{name}: unparseable")
            continue
        if not data:
            bad.append(f"{name}: empty")
    if bad:
        return (bad + ["run `klc update --force` to rebuild the planning views"], "fail")
    return ([], "pass")


def degraded(index_dir: Path) -> tuple[list[str], str]:
    """KLC-106 AC-15: warn-only, reads the persisted per-artifact coverage
    verdicts (`index_coverage.collect_verdicts`) — no builder is re-run, and
    escalation to a hard failure is KLC-107's, not this check's. This is the
    "gains teeth when KLC-106 lands" landing this module's own docstring
    anticipated; the shape is now the real one (a verdict record inside an
    artifact's own `errors[]`), not the two speculative shapes this function
    used to guess at."""
    pre = _uninitialised(index_dir)
    if pre:
        return pre
    verdicts = index_coverage.collect_verdicts(index_dir)
    bad = [index_coverage.render_error(v) for v in verdicts if v.get("degraded")]
    if bad:
        return (bad, "warn")
    if not verdicts:
        return (["degradation metadata is not present — no builder artifact records a "
                 "coverage verdict yet; run `klc init`/`klc update`"], "pass")
    return ([], "pass")


def hook(project_root: Path, mode: str | None, location: str | None) -> tuple[list[str], str]:
    """AC-5: verify the hook decision `klc install` recorded (settings is
    the ONLY source of truth this check reads — AC-17's spy assertion)."""
    repo = Path(project_root)
    import hook_install
    repair = f"run `klc install {repo} --force` to re-record the hook decision"
    if mode is None:
        return ([f"no hook mode recorded in settings — {repair}"], "warn")
    if mode == "disabled":
        return ([], "pass")
    if mode == "direct":
        hooks_dir = hook_install.resolve_hooks_dir(repo)
        target = (hooks_dir / "pre-commit") if hooks_dir else None
        if target and target.exists() and hook_install.MARKER in target.read_text(
                encoding="utf-8", errors="ignore"):
            return ([], "pass")
        det = hook_install.detect(repo)
        return ([f"settings records hook_mode=direct at {location}, but no klc "
                 f"invocation is reachable from {hooks_dir} — {repair}",
                 hook_install.render_snippet(det["manager"], "klc update")], "fail")
    det = hook_install.detect(repo)
    if hook_install.manager_config_mentions_klc(repo, det["manager"]):
        return ([], "pass")
    return ([f"settings records hook_mode=snippet for {det['manager']}, but no klc "
             f"invocation appears in its configuration — {repair}",
             hook_install.render_snippet(det["manager"], "klc update")], "warn")
