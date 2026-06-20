"""track_classifier.py — symmetric, evidence-gated track classification.

Two pure functions:
  is_downgrade_safe(affected_modules, modules_index) -> (bool, dict)
  final_track(floor, estimate, downgrade_safe) -> (track, reason)

KLC-028: separates the downgrade gate from the prompt so it can be
enforced by can_complete_discovery (step-3) rather than just advised.
"""
from __future__ import annotations

_TRACK_ORDER: dict[str, int] = {"XS": 0, "S": 1, "M": 2, "L": 3}
_TRACKS: list[str] = ["XS", "S", "M", "L"]

# Ordered low→high. (track, inclusive_max_total). L is the open-ended top.
TRACK_THRESHOLDS: list[tuple[str, int | None]] = [("XS", 2), ("S", 5), ("M", 8), ("L", None)]


def _track_for_total(total: int) -> str:
    for name, hi in TRACK_THRESHOLDS:
        if hi is None or total <= hi:
            return name
    return "L"


def _rank(track: str) -> int:
    return _TRACK_ORDER.get(track, 1)


def _by_rank(rank: int) -> str:
    return _TRACKS[max(0, min(rank, len(_TRACKS) - 1))]


def is_downgrade_safe(
    affected_modules: list[str],
    modules_index: dict,
) -> tuple[bool, dict]:
    """Return (True, info) iff a downgrade below the intake floor is safe.

    Safe means: for every affected module, depended_by is known, AND
    the union of all external dependents (depended_by − affected_set) is empty.

    Returns (False, {reason: str}) on any evidence gap.
    Returns (True, {external_dependents: []}) when the gate passes.
    """
    # C-001: absence of evidence must never be treated as low impact.
    if not affected_modules:
        return False, {"reason": "no affected modules; blast-radius unavailable"}

    modules: list[dict] = modules_index.get("modules", [])
    by_name: dict[str, dict] = {m["name"]: m for m in modules if "name" in m}
    affected_set = set(affected_modules)

    external: list[str] = []
    for mod_name in affected_modules:
        entry = by_name.get(mod_name)
        if entry is None:
            return False, {"reason": f"module '{mod_name}' not found in index"}
        if "depended_by" not in entry:
            return False, {"reason": f"module '{mod_name}' has no depended_by key"}
        for dep in entry["depended_by"]:
            if dep not in affected_set:
                external.append(dep)

    if external:
        return False, {"reason": "external dependents present", "external_dependents": external}

    return True, {"external_dependents": []}


def final_track(
    floor: str,
    estimate: dict,
    downgrade_safe: bool,
) -> tuple[str, str]:
    """Compute the final track from the intake floor, estimate, and downgrade gate.

    Upward overrides (applied on top of the total-derived band):
      - any axis (complexity/uncertainty/risk/manual) = 3 → at least M
      - uncertainty = 3 AND total ≥ 7 → L

    Downgrade: track < floor only when downgrade_safe is True.
    """
    complexity = estimate.get("complexity", 1)
    uncertainty = estimate.get("uncertainty", 1)
    risk = estimate.get("risk", 1)
    manual = estimate.get("manual", 0)
    total = estimate.get("total", complexity + uncertainty + risk + manual)

    # Derive band from total
    band = _track_for_total(total)

    # Upward overrides
    axes = [complexity, uncertainty, risk, manual]
    if any(a >= 3 for a in axes):
        if _rank(band) < _rank("M"):
            band = "M"

    if uncertainty >= 3 and total >= 7:
        band = "L"

    # Enforce floor (or allow downgrade when safe)
    if _rank(band) < _rank(floor):
        if downgrade_safe:
            reason = f"downgrade {floor}→{band} approved (zero external dependents)"
            return band, reason
        else:
            reason = f"held at floor {floor} (blast-radius unavailable or not low)"
            return floor, reason

    reason = f"track={band} (floor={floor}, total={total})"
    return band, reason
