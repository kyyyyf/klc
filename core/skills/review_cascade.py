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

    def as_dict(self) -> dict:
        return {
            "use_full_review":  self.use_full_review,
            "reason":           self.reason,
            "tier":             self.tier,
            "sentinel_hits":    self.sentinel_hits,
            "scope_drift":      self.scope_drift,
            "scope_expansion":  self.scope_expansion,
        }


def _run_skill(script_name: str, *args: str) -> dict:
    """Run a skill subprocess and return its stdout parsed as JSON."""
    skill = framework_root() / "core" / "skills" / script_name
    try:
        r = subprocess.run(
            [sys.executable, str(skill), *args],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode not in (0, 1, 2) or not r.stdout.strip():
            return {}
        return json.loads(r.stdout)
    except Exception:
        return {}


def _get_sentinel_hits(diff_path: Path) -> int:
    result = _run_skill("scan_sentinels.py", "--diff", str(diff_path), "--format", "json")
    return result.get("summary", {}).get("total", 0)


def _get_file_tiers(diff_path: Path) -> dict[str, str]:
    result = _run_skill("classify_tier.py", "--diff", str(diff_path), "--format", "json")
    return {f["path"]: f["tier"] for f in result.get("files", [])}


def _highest_tier(tiers: dict[str, str]) -> str:
    order = {"critical": 3, "core": 2, "peripheral": 1}
    if not tiers:
        return "unknown"
    top = max(tiers.values(), key=lambda t: order.get(t, 0))
    return top


def decide(ticket: str, diff_path: Path) -> CascadeDecision:
    """Run the cascade pipeline and return a routing decision.

    Falls back to full review on any error (safe default).
    """
    # Load cascade config
    cascade_cfg = _load_cascade_config()
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
    threshold = cascade_cfg.get("peripheral_max_files",
                                _DEFAULT_PERIPHERAL_MAX_FILES)
    peripheral_count = sum(1 for t in file_tiers.values() if t == "peripheral")

    if drift and not skipped_scope:
        return CascadeDecision(
            use_full_review=True,
            reason=f"scope drift (unplanned modules): {drift}",
            tier=top_tier or "peripheral",
            scope_drift=drift,
            file_tiers=file_tiers,
        )

    if file_tiers and peripheral_count > threshold:
        return CascadeDecision(
            use_full_review=True,
            reason=f"too many peripheral files ({peripheral_count} > {threshold})",
            tier="peripheral",
            file_tiers=file_tiers,
        )

    return CascadeDecision(
        use_full_review=False,
        reason="peripheral diff, no sentinels, no scope drift → cheap review",
        tier=top_tier or "peripheral",
        scope_drift=drift,
        file_tiers=file_tiers,
    )


_DEFAULT_PERIPHERAL_MAX_FILES = 20


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
