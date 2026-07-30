#!/usr/bin/env python3
"""elicitation_techniques.py — reader/picker for config/elicitation-techniques.csv.

The elicitation catalog is the HOW to the coverage taxonomy's WHAT (KLC-086): a set of
named, serious interrogation techniques that discovery (E-03, KLC-090) and the later
design review will surface at a natural pause. This module is the ONE place that loads the
machine-form CSV, so callers reference techniques through the picker and never re-parse the
file themselves (single-source-of-truth). It mirrors `core/skills/coverage_taxonomy.py`
exactly in shape — project-override resolver, package-safe import, degrade-not-fail
accessors — but the file is a CSV, so it parses with the standard-library `csv` module and
there is deliberately no private `_yaml` dance to reproduce (C-001).

It ships DATA plus a tiny reader/picker, not a rule engine. `pick` keeps the catalog out of
the caller's context: it maps a context hint to a couple of relevant categories, then hands
back at most `n` rows drawn across them — never the whole catalog. The public API is
selection ONLY — `load`, `by_category`, `pick`, `should_offer` — with NO apply/run/execute
entrypoint, so a surfaced technique is executed by the caller only after a human yes
(never-apply-without-a-yes, C-004).

Degrade-not-fail (C-002): a missing or malformed CSV must never crash a consumer. `load()`
is the strict, single-source read and may raise; the consumer-facing accessors
(`by_category`, `pick`) catch OSError/ValueError and return `[]`, so a picker call with no
catalog present is a clean no-op — the picker simply offers nothing.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports (mirrors coverage_taxonomy.py).
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
from core.shared.paths import framework_root, klc_config_dir  # noqa: E402

# The five columns every catalog row carries.
_COLUMNS = ("id", "name", "category", "description", "output_pattern")

# Context signal -> the categories the picker leans toward. A hint that matches nothing
# falls back to the balanced default below, so pick always has a pool to draw from.
_CONTEXT_CATEGORIES = {
    "risk": ["risk", "technical"],
    "launch": ["risk", "technical"],
    "code": ["technical", "core"],
    "design": ["technical", "framing"],
    "stakeholders": ["collaboration", "framing"],
    "ideation": ["creative", "framing"],
}
_DEFAULT_CATEGORIES = ["core", "framing", "risk"]  # balanced when the hint says nothing

# The picker is a HARD track-gate — offered only on these tracks by default (C-003).
_GATED_TRACKS = {"M", "L"}


def techniques_path() -> Path:
    """Path to the catalog CSV, project override winning over the framework copy.

    `.klc/config/elicitation-techniques.csv` shadows `config/elicitation-techniques.csv`
    when present, exactly like taxonomy_path() resolves its override.
    """
    override = klc_config_dir() / "elicitation-techniques.csv"
    if override.exists():
        return override
    return framework_root() / "config" / "elicitation-techniques.csv"


def _is_complete(row: dict) -> bool:
    """A row is usable only when ALL five required columns are present and non-empty.

    A project override could carry a row with an id/category but a blank (or missing)
    name/description/output_pattern; serving it would hand a consumer a dict missing a
    contract key and crash offer-rendering on a KeyError instead of degrading. Such rows
    are dropped, so `pick`/`by_category` never return an incomplete dict (codex-P2).
    """
    return all(isinstance(row.get(c), str) and row.get(c).strip() for c in _COLUMNS)


def load() -> list[dict]:
    """Return the catalog as a list of row dicts (id/name/category/description/
    output_pattern), each carrying all five columns non-empty. Strict single-source read:
    raises FileNotFoundError when the file is absent and ValueError when it is malformed or
    carries no usable rows. Rows missing a required column are dropped; if that leaves no
    rows, the file is treated as having no rows (a normal degrade for the accessors)."""
    path = techniques_path()
    if not path.exists():
        raise FileNotFoundError(f"elicitation-techniques: {path} not found")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if _is_complete(r)]
    if not rows:
        raise ValueError(f"elicitation-techniques: {path} has no rows")
    return rows


def by_category(category: str) -> list[dict]:
    """Rows of the given category, or [] when the file is absent, malformed, or the
    category is unknown (degrade-not-fail).

    Catches OSError (covers FileNotFoundError, plus IsADirectoryError / PermissionError
    when techniques_path() resolves to a directory or an unreadable file), ValueError
    (no usable rows, plus UnicodeDecodeError), and csv.Error — a direct Exception subclass
    (NOT OSError/ValueError) raised for parser-level malformations such as an oversized
    field. Nothing raised here reaches a consumer.
    """
    try:
        return [r for r in load() if r.get("category") == category]
    except (OSError, ValueError, csv.Error):
        return []


def _categories_for(context: object) -> list[str]:
    """Map a context hint to its lean-toward categories, or [] when nothing matches."""
    if not isinstance(context, str):
        return []
    return _CONTEXT_CATEGORIES.get(context.strip().lower(), [])


def _spread(pool: list[dict], categories: list[str], n: int) -> list[dict]:
    """Round-robin one row per category across `categories`, capped at `n`, so the draw
    is balanced rather than front-loaded on whichever category the CSV lists first."""
    buckets: dict[str, list[dict]] = {c: [] for c in categories}
    for row in pool:
        cat = row.get("category")
        if cat in buckets:
            buckets[cat].append(row)
    result: list[dict] = []
    idx = 0
    while len(result) < n:
        took = False
        for cat in categories:
            bucket = buckets[cat]
            if idx < len(bucket):
                result.append(bucket[idx])
                took = True
                if len(result) >= n:
                    break
        if not took:
            break
        idx += 1
    return result


def pick(context: object, n: int = 5) -> list[dict]:
    """Hand back at most `n` context-relevant technique rows — never the whole catalog.

    Maps the context hint to a couple of categories (falling back to a balanced default
    when the hint says nothing), filters the catalog to those, and spreads the draw across
    them capped at `n`. Degrade-not-fail: returns [] when the catalog is absent or
    malformed, so an offer with no catalog present is a clean no-op.

    This is SELECTION only — it returns candidates for the caller to offer, not a result of
    applying them. There is deliberately no apply()/run() here (C-004).
    """
    categories = _categories_for(context) or _DEFAULT_CATEGORIES
    try:
        pool = [r for r in load() if r.get("category") in categories]
    except (OSError, ValueError, csv.Error):
        return []
    return _spread(pool, categories, n)


def should_offer(track: str, flagged_ambiguity: bool = False) -> bool:
    """HARD track-gate (C-003): should the picker be offered for this ticket at all?

    Returns True only when `track` is M or L, OR when the caller sets
    `flagged_ambiguity`. XS and S with no flag return False, so the picker never fires
    on small tickets by default — this is the mitigation for the deliberate
    "include the catalog now" decision, which would otherwise over-ceremony small
    tickets. The flagged-ambiguity escape is the SOLE path onto XS/S and must be an
    explicit signal from the caller, never a default; an unknown track string is
    fail-closed (False) unless that flag is set.

    This gate is selection metadata only. There is deliberately no apply()/run() in this
    module — a surfaced technique is executed by the caller only after a human yes
    (never-apply-without-a-yes, C-004).
    """
    if flagged_ambiguity:
        return True
    return track in _GATED_TRACKS


if __name__ == "__main__":
    for _r in load():
        print(f"{_r.get('category', '?'):14} {_r.get('id')}")
