"""ticket_id.py — the ONE loader of the ticket-key pattern (KLC-172 review F-012).

Why: three call sites each hand-rolled a parser of `ticket-id.yml` with
slightly different quoting rules. This module is the single reader.

Resolution order: the project's `.klc/config/ticket-id.yml`, then the
framework's `config/ticket-id.yml`, then the Jira-style default. A missing,
unreadable or malformed file falls through to the next source.

    key_pattern()  -> the anchored pattern (use `.match` on a whole name)
    find_keys(txt) -> every key-shaped token inside free text (word-bounded)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

import _paths  # noqa: E402

DEFAULT_PATTERN = r"^[A-Z][A-Z0-9]+-\d+$"


def _read_pattern(cfg: Path) -> str | None:
    """The `pattern:` value of one yml file, with YAML quoting honoured by hand
    (single quotes literal, double quotes obey backslash escapes); None when
    the file is absent or names no pattern."""
    try:
        lines = cfg.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line.startswith("pattern:"):
            continue
        v = line.split(":", 1)[1].strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            quote, v = v[0], v[1:-1]
            if quote == '"':
                v = v.encode("utf-8").decode("unicode_escape")
        return v or None
    return None


def _source() -> str:
    for cfg in (_paths.klc_config_dir() / "ticket-id.yml",
                _paths.framework_root() / "config" / "ticket-id.yml"):
        raw = _read_pattern(cfg)
        if raw is None:
            continue
        try:
            re.compile(raw)
        except re.error:
            continue
        return raw
    return DEFAULT_PATTERN


def key_pattern() -> re.Pattern:
    """The configured ticket-key pattern (anchored, as written in the yml)."""
    return re.compile(_source())


def find_keys(text: str) -> list[str]:
    """Every ticket-key-shaped token in *text*, in order of appearance. The
    anchors are stripped so the pattern works inside free text, and a word
    boundary keeps `XUTF-8x` from yielding `UTF-8`."""
    raw = _source().removeprefix("^").removesuffix("$")
    try:
        rx = re.compile(rf"\b(?:{raw})\b")
    except re.error:
        rx = re.compile(rf"\b(?:{DEFAULT_PATTERN[1:-1]})\b")
    return [m.group(0) for m in rx.finditer(text or "")]
