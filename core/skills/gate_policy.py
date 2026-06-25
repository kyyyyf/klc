"""gate_policy.py — gate classification and auto-proceed predicate (KLC-045).

Two public surfaces:
  evaluate(gate, signals) -> GateDecision   — pure predicate, no I/O
  collect_signals(ticket, phase_id) -> dict — assembles signals from real skills

Gate levels (set per-pick in phases.yml):
  auto        — always proceed silently (no signals checked)
  conditional — proceed only when all signals are clean; missing key = dirty
  decision    — always pause; human judgment required

Fail-closed: any signal key absent from the signals dict is treated as dirty,
not clean. The collector is the only place with I/O; evaluate stays pure.
"""
from __future__ import annotations

import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Ensure skills directory is on path for bare imports
_skills_dir = Path(__file__).resolve().parent
if str(_skills_dir) not in sys.path:
    sys.path.insert(0, str(_skills_dir))


# ---------------------------------------------------------------------------
# GateDecision
# ---------------------------------------------------------------------------

@dataclass
class GateDecision:
    proceed: bool
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# evaluate() — pure predicate (no I/O)
# ---------------------------------------------------------------------------

_REQUIRED_SIGNALS = (
    "advisory",
    "scope_expansion",
    "sentinels",
    "mutation",
    "budget_overrun",
    "verdict",
    "route_confidence",
)

# A signal is clean only when present AND its checker passes; absent => dirty.
_CHECK = {
    "advisory":        lambda v: not v,
    "scope_expansion": lambda v: v is False,
    "sentinels":       lambda v: v is False,
    "mutation":        lambda v: v is False,
    "budget_overrun":  lambda v: v is False,
    "verdict":         lambda v: v in ("approve", "APPROVED", "PASS", "clean"),
    "route_confidence": lambda v: v in ("high", "medium"),
}


def evaluate(gate: str, signals: dict) -> GateDecision:
    """Return a GateDecision for the given gate level and collected signals.

    - auto      → always proceed
    - decision  → always pause (human required)
    - conditional → proceed only when every required signal is present and clean
    """
    if gate == "auto":
        return GateDecision(True, [])
    if gate == "decision":
        return GateDecision(False, ["decision gate — human required"])
    # conditional: every required key must be present and pass its check
    bad = [
        k for k in _REQUIRED_SIGNALS
        if k not in signals or not _CHECK[k](signals[k])
    ]
    return GateDecision(not bad, [f"{k} not clean" for k in bad])


# ---------------------------------------------------------------------------
# collect_signals() — assembles the signals dict from real skill APIs
# ---------------------------------------------------------------------------

def _budget_at_limit(ticket: str, counter: str) -> bool:
    import budget as _budget
    import lifecycle as _lc
    limits = _budget._load_limits()
    cur = (_lc.read_meta(ticket).get("budgets") or {})
    return int(cur.get(counter, 0)) >= limits.get(counter, 10 ** 9)


def _sentinel_hits(ticket: str) -> bool:
    """True when the git diff for this ticket's branch contains a sentinel hit.

    Any error (no git, no diff) → dirty (True, fail-closed).
    """
    import scan_sentinels as _ss
    import subprocess
    try:
        config = _ss.load_sentinels_config()
        result = subprocess.run(
            ["git", "diff", "main..HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return True  # can't get diff → dirty
        diff_text = result.stdout
        if not diff_text.strip():
            return False  # no diff → no hits
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".diff", delete=False, encoding="utf-8"
        ) as f:
            f.write(diff_text)
            diff_path = Path(f.name)
        try:
            hits = _ss.scan_diff(diff_path, config)
            return bool(hits)
        finally:
            diff_path.unlink(missing_ok=True)
    except Exception:
        return True  # any error → dirty


def _read_verdict(ticket: str) -> str:
    """Read review-report.md and return the verdict string.

    Returns "APPROVED" when the ## Verdict section contains PASS/APPROVED
    and no CHANGES_REQUESTED / NEEDS_FIX. Any other case returns a dirty value.
    Missing file → dirty ("NO_REPORT").
    """
    from _paths import klc_ticket_dir
    report = klc_ticket_dir(ticket) / "review-report.md"
    try:
        text = report.read_text(encoding="utf-8")
    except OSError:
        return "NO_REPORT"

    # Find ## Verdict section
    m = re.search(r"##\s+Verdict\s*\n(.*?)(?=\n##|\Z)", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return "NO_VERDICT_SECTION"
    verdict_block = m.group(1)

    has_approve = bool(re.search(r"\b(APPROVED|PASS|approve|clean)\b", verdict_block))
    has_reject = bool(re.search(
        r"\b(CHANGES[_ ]REQUESTED|NEEDS[_ ]FIX|REQUEST[_ ]CHANGES|REJECTED)\b",
        verdict_block, re.IGNORECASE,
    ))
    if has_approve and not has_reject:
        return "APPROVED"
    return "CHANGES_REQUESTED"


def collect_signals(ticket: str, phase_id: str) -> dict:
    """Assemble all seven gate signals for the given ticket and phase.

    Signal keys:
      advisory         — str; empty string when clean
      scope_expansion  — bool; True when unplanned modules were touched
      sentinels        — bool; True when a sentinel was hit in the diff
      mutation         — bool; True when mutation_fix_attempts counter is at limit
      budget_overrun   — bool; True when any budget counter is at limit
      verdict          — str; "APPROVED" when review verdict is clean
      route_confidence — str; only present when set in meta (absent → dirty in evaluate)

    Any unavailable source yields a dirty value (fail-closed).
    """
    import phase_completion as _pc
    import scope_delta as _sd
    import budget as _budget
    import lifecycle as _lc

    # advisory
    try:
        _, advisory = _pc.can_complete(ticket, phase_id)
    except Exception:
        advisory = "phase_completion_error"

    # scope_expansion
    try:
        delta = _sd.compare(ticket)
        scope_expansion = bool(delta.get("expansion") or delta.get("skipped"))
    except Exception:
        scope_expansion = True  # dirty

    # sentinels
    sentinels = _sentinel_hits(ticket)

    # mutation
    try:
        mutation = _budget_at_limit(ticket, "mutation_fix_attempts")
    except Exception:
        mutation = True

    # budget_overrun
    try:
        budget_overrun = any(
            _budget_at_limit(ticket, c) for c in _budget._load_limits()
        )
    except Exception:
        budget_overrun = True

    # verdict
    verdict = _read_verdict(ticket)

    sig: dict = {
        "advisory":        advisory or "",
        "scope_expansion": scope_expansion,
        "sentinels":       sentinels,
        "mutation":        mutation,
        "budget_overrun":  budget_overrun,
        "verdict":         verdict,
    }

    # route_confidence: absent from meta → key omitted (evaluate treats missing as dirty)
    try:
        rc = _lc.read_meta(ticket).get("route_confidence")
        if rc is not None:
            sig["route_confidence"] = rc
    except Exception:
        pass  # omit → dirty in evaluate

    return sig
