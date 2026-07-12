#!/usr/bin/env python3
"""budget_guard.py — prompt-size budget helpers, shared by runner.py and
the orchestrator (KLC-052).

Moved out of runner.py verbatim (behavior preserved) so an advisory,
non-dispatching check (`check_prompt_budget`) can be reused by the
orchestrator loop before it even attempts a dispatch, instead of only
being enforced inline inside `run_agent`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


# --- budget loading ------------------------------------------------------------

def load_budget_limits() -> tuple[dict[str, int], dict[str, int]]:
    """Return (soft_limits, hard_limits) from config/budgets.yml.

    Supports both the new soft_limits/hard_limits keys and the legacy
    prompt_input_limits key (treated as hard limit only).
    """
    try:
        import yaml
        from _paths import framework_root
        path = framework_root() / "config" / "budgets.yml"
        if not path.exists():
            return {}, {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        soft = {k: int(v) for k, v in (data.get("soft_limits") or {}).items()}
        hard = {k: int(v) for k, v in (data.get("hard_limits") or {}).items()}
        # legacy fallback
        if not hard and not soft:
            legacy = {k: int(v) for k, v in
                      (data.get("prompt_input_limits") or {}).items()}
            return {}, legacy
        return soft, hard
    except Exception:
        return {}, {}


# --- token telemetry helpers ----------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars."""
    return max(1, len(text) // 4)


def write_token_metrics(ticket: str | None, phase_id: str,
                         tokens_in: int, tokens_out: int,
                         cache_hit: int, source: str = "estimated") -> None:
    """Persist token counts into meta.json:metrics.tokens.<phase_id>.

    source: "provider" when parsed from real API usage block,
            "estimated" when derived from len(text)//4.
    cache_hit is always 0 for estimated source.
    """
    if not ticket:
        return
    try:
        from _paths import klc_ticket_meta_file
        meta_path = klc_ticket_meta_file(ticket)
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        metrics = meta.setdefault("metrics", {})
        tokens = metrics.setdefault("tokens", {})
        tokens[phase_id] = {
            "in":        tokens_in,
            "out":       tokens_out,
            "cache_hit": cache_hit if source == "provider" else 0,
            "source":    source,
        }
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass  # telemetry is non-fatal


# --- advisory budget check (KLC-052) --------------------------------------------

@dataclass
class BudgetVerdict:
    hard_breach: bool
    soft_breach: bool
    estimated:   int
    limit:       int | None


def check_prompt_budget(track: str, estimated: int) -> BudgetVerdict:
    """Advisory check: does `estimated` tokens breach the soft/hard
    limit for `track`? Does not dispatch or write anything — callers
    (e.g. the orchestrator) decide what to do with the verdict."""
    soft_limits, hard_limits = load_budget_limits()
    hard = hard_limits.get(track)
    soft = soft_limits.get(track)
    return BudgetVerdict(
        hard_breach=bool(hard and estimated > hard),
        soft_breach=bool(soft and estimated > soft),
        estimated=estimated,
        limit=hard,
    )
