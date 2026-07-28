#!/usr/bin/env python3
"""spec_saoc.py — the structured acceptance-criterion format (Codespeak SAOC).

An acceptance criterion is written as four segments separated by a middle dot
`·` (U+00B7):

    AC-1: <Subject> · <Action> · <Object> · <Condition>

* Subject   — the actor / component the requirement is about.
* Action    — the observable verb it performs.
* Object    — what the action operates on / produces.
* Condition — the verifiable trigger or expected outcome ("when …", "then …").

Splitting an AC into these four named parts is what makes it objectively
checkable for completeness (all four present) and testability (the Condition
names something observable). This module is JUST the recogniser + validator —
a lightweight convention and a checker, deliberately NOT a DSL. The deterministic
gate (`spec_selfcheck.py`) and the spec reviewer (KLC-084) build on top of it.

Design notes:
* The separator is the middle dot on purpose: it is visually unobtrusive in
  prose, is not something a normal English AC line already contains, and gives
  a single unambiguous split point (unlike commas, which appear inside clauses).
* Recognition is line-oriented and tolerant of the two AC list styles the spec
  agents emit: a `- [ ] AC-1: …` checklist item (discovery-lite) and a
  `1. AC-1: …` numbered item (full discovery), plus a bare `AC-1: …` line.
* Unicode look-alikes for the middle dot (bullet `•`, dot operator `⋅`, katakana
  middle dot `・`, …) are normalised to `·` before the split, so an AC that
  clearly INTENDS SAOC is not scored malformed over a typographic near-miss.
* Known limitation (no escaping): a literal `·` INSIDE one of the four parts is
  indistinguishable from a separator, so it over-splits the AC. Keep a part free
  of middle dots — reword rather than trying to escape one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# The canonical SAOC segment separator (MIDDLE DOT, U+00B7).
SEP = "·"

# Unicode look-alikes normalised to the canonical SEP before splitting. Each is a
# glyph an author might type instead of U+00B7; treating them as the separator
# keeps an intended-SAOC AC from being falsely flagged malformed.
_SEP_LOOKALIKES = {
    "•": SEP,   # U+2022 BULLET
    "⋅": SEP,   # U+22C5 DOT OPERATOR
    "∙": SEP,   # U+2219 BULLET OPERATOR
    "‧": SEP,   # U+2027 HYPHENATION POINT
    "・": SEP,  # U+30FB KATAKANA MIDDLE DOT
    "･": SEP,   # U+FF65 HALFWIDTH KATAKANA MIDDLE DOT
    "\u0387": SEP,  # U+0387 GREEK ANO TELEIA (distinct codepoint from U+00B7)
}
_SEP_TRANS = str.maketrans(_SEP_LOOKALIKES)

# The four named parts, in order.
PARTS = ("subject", "action", "object", "condition")

# Recognise an AC line under any of the emitted list styles. Capture the id
# (AC-<n>) and the remaining body after the colon. Anchored per-line.
_AC_LINE_RE = re.compile(
    r"^[ \t]*"
    r"(?:[-*][ \t]*\[[ xX]\][ \t]*|\d+\.[ \t]*)?"  # optional "- [ ] " or "1. "
    r"(AC-\d+)"                                        # id
    r"[ \t]*:[ \t]*"                                   # colon
    r"(.*\S)?[ \t]*$",                                 # body (may be empty)
    re.MULTILINE,
)

# Vague words that make a Condition non-verifiable ("works correctly" is not a
# test). Used by the testability heuristic; deliberately small and surfaced,
# never a hard fail.
_VAGUE_TOKENS = (
    "correctly", "properly", "appropriately", "as expected", "as needed",
    "reasonable", "reasonably", "gracefully", "sensible", "sensibly",
    "works", "work well", "etc", "and so on", "somehow", "if needed",
    "user-friendly", "intuitive", "nicely", "good", "better", "fast enough",
)
_MIN_CONDITION_LEN = 8


@dataclass
class AC:
    """One parsed acceptance criterion line."""

    id: str
    body: str
    lineno: int
    parts: list[str] = field(default_factory=list)  # segments, stripped

    @property
    def subject(self) -> str:
        return self.parts[0] if len(self.parts) > 0 else ""

    @property
    def action(self) -> str:
        return self.parts[1] if len(self.parts) > 1 else ""

    @property
    def object(self) -> str:
        return self.parts[2] if len(self.parts) > 2 else ""

    @property
    def condition(self) -> str:
        return self.parts[3] if len(self.parts) > 3 else ""

    @property
    def is_wellformed(self) -> bool:
        """True iff the body has exactly four non-empty SAOC segments."""
        return len(self.parts) == 4 and all(p.strip() for p in self.parts)

    def missing_parts(self) -> list[str]:
        """Names of the SAOC parts that are absent or empty.

        A body with the wrong segment count reports every part beyond what was
        supplied as missing; an empty segment reports that named part.
        """
        missing: list[str] = []
        for i, name in enumerate(PARTS):
            if i >= len(self.parts) or not self.parts[i].strip():
                missing.append(name)
        # Too many segments is also malformed; flag it explicitly.
        if len(self.parts) > 4:
            missing.append(f"extra-segments({len(self.parts)})")
        return missing


def _split_parts(body: str) -> list[str]:
    """Split an AC body on the SAOC separator, stripping each segment.

    Look-alike separators are normalised to `·` first so an AC that meant SAOC
    but typed a bullet/dot-operator is still split into its four parts.
    """
    if not body:
        return []
    return [seg.strip() for seg in body.translate(_SEP_TRANS).split(SEP)]


def parse_ac_line(line: str) -> AC | None:
    """Parse a single line into an AC, or None if it is not an AC line."""
    m = _AC_LINE_RE.match(line)
    if not m:
        return None
    body = (m.group(2) or "").strip()
    return AC(id=m.group(1), body=body, lineno=1, parts=_split_parts(body))


def parse_acs(text: str) -> list[AC]:
    """Return every AC line found in *text*, in document order."""
    acs: list[AC] = []
    for m in _AC_LINE_RE.finditer(text):
        body = (m.group(2) or "").strip()
        lineno = text.count("\n", 0, m.start()) + 1
        acs.append(AC(id=m.group(1), body=body, lineno=lineno, parts=_split_parts(body)))
    return acs


def malformed(text: str) -> list[AC]:
    """ACs that are not in well-formed SAOC form (deterministic format check)."""
    return [ac for ac in parse_acs(text) if not ac.is_wellformed]


def weak_condition(condition: str) -> str | None:
    """Return a reason string if the Condition is not verifiably testable, else None.

    Heuristic (surfaced, never a hard fail): a Condition is weak when it is too
    short to name anything observable, or leans on a vague quality word instead
    of a checkable trigger/outcome. Genuine testability is a judgment call that
    belongs to the spec reviewer (KLC-084); this only flags the obvious cases.
    """
    c = condition.strip()
    if len(c) < _MIN_CONDITION_LEN:
        return "condition too short to be verifiable"
    low = c.lower()
    for tok in _VAGUE_TOKENS:
        if re.search(r"(?<![\w-])" + re.escape(tok) + r"(?![\w-])", low):
            return f"vague condition term: {tok!r}"
    return None


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description="SAOC acceptance-criterion checker")
    ap.add_argument("--file", required=True)
    args = ap.parse_args()
    acs = parse_acs(Path(args.file).read_text(encoding="utf-8"))
    out = [
        {
            "id": ac.id,
            "wellformed": ac.is_wellformed,
            "missing": ac.missing_parts(),
            "weak_condition": weak_condition(ac.condition) if ac.is_wellformed else None,
        }
        for ac in acs
    ]
    print(json.dumps({"acs": out}, indent=2, ensure_ascii=False))
    raise SystemExit(1 if any(not ac.is_wellformed for ac in acs) else 0)
