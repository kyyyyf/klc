#!/usr/bin/env python3
"""review_cascade.py — decide review depth based on diff signals.

Pipeline:
    scope_delta  →  scan_sentinels  →  classify_tier  →  CascadeDecision

Decision rules (first match wins):
  1. Sentinel hits present          → full review (CRITICAL risk)
  2. Scope expansion present        → full review (unplanned modules touched)
  3. Any critical-tier file         → full review
  4. Any core-tier file             → full review
  5. All peripheral + no drift      → cheap review (single Sonnet agent)

KLC-175: the decision also carries `layers`, the three-layer plan of the
review: layer 0 = the deterministic checks (never a pass), layer 1 = exactly
one `code-review` reviewer, layer 2 = the specialists whose signal is present
in the diff (empty when none is). The depth rules above only set
`use_full_review` (the recorded review depth); they no longer pick reviewers.

Returns a CascadeDecision dataclass that review.py / runner.py can act on.

API:
    decide(ticket, diff_path) -> CascadeDecision

CLI:
    python core/skills/review_cascade.py <ticket> <diff.patch>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_file_dir))

from core.shared.paths import framework_root, klc_index_dir  # noqa: E402
import lifecycle as _lc  # noqa: E402


@dataclass
class CascadeDecision:
    use_full_review: bool          # True = existing multi-agent, False = cheap single
    reason: str                    # human-readable explanation
    tier: str                      # "peripheral" | "core" | "critical" | "mixed" | "unknown"
    sentinel_hits: int = 0
    scope_drift: list[str] = field(default_factory=list)
    scope_expansion: list[str] = field(default_factory=list)
    file_tiers: dict[str, str] = field(default_factory=dict)  # path → tier
    diff_files: int = 0            # total changed files
    diff_lines: int = 0            # total added + removed lines
    # KLC-175: {"layer0": [check names], "layer1": "code-review",
    # "layer2": [specialist names]}. Empty = derive from signals (a decision
    # built by hand, e.g. in a test, still plans one code-review pass).
    layers: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "use_full_review":  self.use_full_review,
            "reason":           self.reason,
            "tier":             self.tier,
            "sentinel_hits":    self.sentinel_hits,
            "scope_drift":      self.scope_drift,
            "scope_expansion":  self.scope_expansion,
            "diff_files":       self.diff_files,
            "diff_lines":       self.diff_lines,
            "layers":           self.layers or default_layers({}),
            "signals":          self.signals,
        }


SPECIALIST_ORDER = ("security", "architecture", "performance", "deep-impact")


def _on(signals: dict, *names: str) -> bool:
    """A signal is "on" when it is True OR None (unevaluable): an unevaluable
    signal plans its specialist, never reads as "no risk" (fail closed). A name
    the dict does not hold at all is off."""
    return any(n in signals and (signals[n] is None or bool(signals[n])) for n in names)


def specialists_for(signals: dict) -> list[str]:
    """Layer 2: the specialists whose signal is present (AC-4) or could not be
    evaluated (None, fail closed). Empty when no signal fired."""
    out: list[str] = []
    if _on(signals, "sentinel_hit", "critical_tier"):
        out.append("security")
    if _on(signals, "changed_public_api", "dependency_edge_added"):
        out.append("architecture")
    if _on(signals, "hot_path"):
        out.append("performance")
    if _on(signals, "deep_impact"):
        out.append("deep-impact")
    return out


def _layer0_names() -> list[str]:
    try:
        import review_layer0
        return [n for n, _ in review_layer0._CHECKS]
    except Exception:
        return ["ac_test_coverage", "tdd_order", "drift_check", "scope_delta",
                "sentinels"]


def default_layers(signals: dict) -> dict:
    """The three-layer plan for *signals* (layer 0 is listed, never a pass)."""
    return {"layer0": _layer0_names(), "layer1": "code-review",
            "layer2": specialists_for(signals)}


def _run_skill(script_name: str, *args: str) -> dict | None:
    """Run a skill subprocess and return its stdout parsed as JSON; None when it
    could not be run or its output is unusable (so a caller can tell "the scan
    failed" from "the scan found nothing")."""
    skill = framework_root() / "core" / "skills" / script_name
    try:
        r = subprocess.run(
            [sys.executable, str(skill), *args],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode not in (0, 1, 2) or not r.stdout.strip():
            return None
        out = json.loads(r.stdout)
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def _get_sentinel_hits(diff_path: Path) -> int | None:
    """The sentinel count of the diff, or None when the scan failed."""
    result = _run_skill("scan_sentinels.py", "--diff", str(diff_path), "--format", "json")
    if result is None:
        return None
    try:
        return int((result.get("summary") or {}).get("total", 0))
    except (TypeError, ValueError):
        return None


def _get_file_tiers(diff_path: Path) -> dict[str, str] | None:
    """path -> tier of the diff's files, or None when the classifier failed."""
    result = _run_skill("classify_tier.py", "--diff", str(diff_path), "--format", "json")
    if result is None:
        return None
    try:
        return {f["path"]: f["tier"] for f in result.get("files", [])}
    except (TypeError, KeyError):
        return None


def _count_diff_lines(diff_path: Path) -> int:
    """Count total added + removed lines in a unified diff."""
    total = 0
    try:
        for line in diff_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                total += 1
            elif line.startswith("-") and not line.startswith("---"):
                total += 1
    except Exception:
        pass
    return total


def _highest_tier(tiers: dict[str, str]) -> str:
    order = {"critical": 3, "core": 2, "peripheral": 1}
    if not tiers:
        return "unknown"
    top = max(tiers.values(), key=lambda t: order.get(t, 0))
    return top


def _thresholds(cascade_cfg: dict) -> tuple[int, int]:
    """(max peripheral files, max peripheral lines) from the flat `cascade`
    keys. They only set the recorded review depth (`use_full_review`)."""
    files = cascade_cfg.get("peripheral_max_files", _DEFAULT_PERIPHERAL_MAX_FILES)
    lines = cascade_cfg.get("peripheral_max_lines", _DEFAULT_PERIPHERAL_MAX_LINES)
    return int(files), int(lines)


def decide(ticket: str, diff_path: Path) -> CascadeDecision:
    """Run the cascade pipeline and return the routing decision plus the
    three-layer plan (`layers`). Falls back to full review on any error."""
    cascade_cfg = _load_cascade_config()
    memo: dict = {}
    real_hits, real_tiers = _get_sentinel_hits, _get_file_tiers

    def _hits(p):
        if "hits" not in memo:
            memo["hits"] = real_hits(p)
        return memo["hits"]

    def _tiers(p):
        if "tiers" not in memo:
            memo["tiers"] = real_tiers(p)
        return memo["tiers"]

    decision = _route(ticket, diff_path, cascade_cfg, _hits, _tiers)
    try:
        from review_signals import signals as _signals
        text = Path(diff_path).read_text(encoding="utf-8", errors="replace") \
            if Path(diff_path).exists() else ""
        hits = _hits(diff_path) if text else 0
        if hits is not None and decision.sentinel_hits:
            hits = max(hits, decision.sentinel_hits)
        tiers = decision.file_tiers or (_tiers(diff_path) if text else {})
        sig = _signals(text, klc_index_dir() / "modules.json", cascade_cfg, tiers,
                       sentinel_hits=hits)
        decision.signals = sig
        decision.layers = default_layers(sig)
    except Exception:
        # The whole signal evaluation failed: every signal is unevaluable, so
        # every specialist is planned (fail closed).
        from review_signals import all_unevaluable
        decision.signals = all_unevaluable()
        decision.layers = default_layers(decision.signals)
    return decision


def _route(ticket: str, diff_path: Path, cascade_cfg: dict,
           _get_sentinel_hits, _get_file_tiers) -> CascadeDecision:  # noqa: F811
    """The depth routing (use_full_review) — the recorded depth only; it picks
    no reviewer."""
    if not cascade_cfg.get("enabled", True):
        return CascadeDecision(
            use_full_review=True,
            reason="cascade disabled in reviewers.yml",
            tier="unknown",
        )

    # --- scope_delta ----------------------------------------------------------
    try:
        import scope_delta as _sd
        delta = _sd.compare(ticket)
    except Exception as exc:
        return CascadeDecision(
            use_full_review=True,
            reason=f"scope_delta failed: {exc}",
            tier="unknown",
        )

    expansion = delta.get("expansion") or []
    drift = delta.get("drift") or []
    skipped_scope = bool(delta.get("skipped"))

    # Fail-closed: unavailable scope check is not the same as "no drift"
    if skipped_scope:
        return CascadeDecision(
            use_full_review=True,
            reason=f"scope comparison unavailable ({delta.get('skipped')}) — defaulting to full review",
            tier="unknown",
            scope_drift=[],
            scope_expansion=[],
        )

    if expansion:
        return CascadeDecision(
            use_full_review=True,
            reason=f"scope expansion: unplanned modules {expansion}",
            tier="unknown",
            scope_expansion=expansion,
            scope_drift=drift,
        )

    # --- scan_sentinels -------------------------------------------------------
    if not diff_path.exists():
        return CascadeDecision(
            use_full_review=True,
            reason=f"diff file not found: {diff_path}",
            tier="unknown",
        )

    sentinel_hits = _get_sentinel_hits(diff_path)
    if sentinel_hits is None:
        return CascadeDecision(
            use_full_review=True,
            reason="sentinel scan unavailable — defaulting to full review",
            tier="unknown",
            scope_drift=drift,
        )
    if sentinel_hits > 0:
        return CascadeDecision(
            use_full_review=True,
            reason=f"{sentinel_hits} sentinel hit(s) — forced full review",
            tier="critical",
            sentinel_hits=sentinel_hits,
            scope_drift=drift,
        )

    # --- classify_tier --------------------------------------------------------
    file_tiers = _get_file_tiers(diff_path)

    # Fail-closed: if classifier returned nothing, we cannot prove peripheral
    if not file_tiers:
        return CascadeDecision(
            use_full_review=True,
            reason="classifier returned no file tiers — cannot prove peripheral; defaulting to full review",
            tier="unknown",
            sentinel_hits=0,
            scope_drift=drift,
        )

    top_tier = _highest_tier(file_tiers)

    if top_tier in ("critical", "core"):
        return CascadeDecision(
            use_full_review=True,
            reason=f"highest tier={top_tier} — full review required",
            tier=top_tier,
            sentinel_hits=0,
            scope_drift=drift,
            file_tiers=file_tiers,
        )

    # --- peripheral + no drift → cheap review --------------------------------
    file_threshold, line_threshold = _thresholds(cascade_cfg)
    peripheral_count = sum(1 for t in file_tiers.values() if t == "peripheral")
    total_lines = _count_diff_lines(diff_path)

    if drift and not skipped_scope:
        return CascadeDecision(
            use_full_review=True,
            reason=f"scope drift (unplanned modules): {drift}",
            tier=top_tier or "peripheral",
            scope_drift=drift,
            file_tiers=file_tiers,
            diff_files=len(file_tiers),
            diff_lines=total_lines,
        )

    if file_tiers and peripheral_count > file_threshold:
        return CascadeDecision(
            use_full_review=True,
            reason=f"too many peripheral files ({peripheral_count} > {file_threshold})",
            tier="peripheral",
            file_tiers=file_tiers,
            diff_files=len(file_tiers),
            diff_lines=total_lines,
        )

    if total_lines > line_threshold:
        return CascadeDecision(
            use_full_review=True,
            reason=(f"peripheral diff too large ({total_lines} lines > {line_threshold}) "
                    f"— full review required ({peripheral_count} files, {total_lines} lines)"),
            tier="peripheral",
            file_tiers=file_tiers,
            diff_files=len(file_tiers),
            diff_lines=total_lines,
        )

    return CascadeDecision(
        use_full_review=False,
        reason=(f"peripheral diff, no sentinels, no scope drift → cheap review "
                f"({peripheral_count} files, {total_lines} lines)"),
        tier=top_tier or "peripheral",
        scope_drift=drift,
        file_tiers=file_tiers,
        diff_files=len(file_tiers),
        diff_lines=total_lines,
    )


_DEFAULT_PERIPHERAL_MAX_FILES = 20
_DEFAULT_PERIPHERAL_MAX_LINES = 500


def _load_cascade_config() -> dict:
    """Load cascade block from config/reviewers.yml."""
    try:
        import yaml
        path = framework_root() / "config" / "reviewers.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("cascade", {})
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ticket", help="Ticket key (e.g. KLC-015)")
    ap.add_argument("diff", type=Path, help="Path to unified diff file")
    args = ap.parse_args()

    decision = decide(args.ticket, args.diff)
    print(json.dumps(decision.as_dict(), indent=2))
    return 0 if not decision.use_full_review else 1


if __name__ == "__main__":
    sys.exit(main())
