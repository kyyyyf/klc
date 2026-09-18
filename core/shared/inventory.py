"""inventory.py — the canonical .klc/index/inventory.json contract (KLC-103).

One statement of the on-disk shape, one reader. Every consumer of the symbol
inventory routes through this module (AC-6) instead of iterating the raw
``symbols`` value itself, so a fourth incompatible reading of the artifact
cannot appear unnoticed.

C-005 / D-2: an ABSENT artifact, or a present artifact this process cannot even
READ (corrupt JSON, I/O error), is a missing-optional-input case and may still
degrade to ``None`` when the caller passes ``required=False`` — that is the
branch two advisory consumers (``planning_validate``, ``planning-retriever``)
rely on today for every optional input, inventory included. A PRESENT,
READABLE artifact carrying the WRONG SHAPE (the retired per-language mapping,
a missing ``symbols`` key, or a non-list) is a schema mismatch, not a missing
input, and always raises regardless of ``required`` — the two paths are
deliberately different branches (AC-7).
"""
from __future__ import annotations

import json
from pathlib import Path

SYMBOL_FIELDS = ("name", "kind", "file", "line", "signature",
                 "visibility", "source_of_truth", "lang", "rule")

CANONICAL_SCHEMA = (
    '{"root": str, "profile": str, '
    '"source_of_truth": {lang: "ast_grep"|"regex"}, '
    '"symbols": [{' + ", ".join(SYMBOL_FIELDS) + '}]  # FLAT, byte-sorted list, '
    '"errors": [str], "notes": [str]}'
)


class InventorySchemaError(ValueError):
    """An inventory carries a retired or unreadable symbol collection."""


def symbols(inventory: dict, *, source: str = "<in-memory inventory>") -> list[dict]:
    """Return the flat symbol list, raising a named, path-carrying error for any
    shape other than the canonical one. Never returns a silent empty default for
    a wrong-shaped input — that is precisely the defect this module exists to
    close (AC-7)."""
    raw = inventory.get("symbols") if isinstance(inventory, dict) else None
    if isinstance(raw, dict):
        raise InventorySchemaError(
            f"{source}: 'symbols' is a per-language mapping (retired pre-KLC-103 "
            f"schema). Expected the canonical flat list: {CANONICAL_SCHEMA}")
    if raw is None:
        raise InventorySchemaError(
            f"{source}: no 'symbols' collection at all. "
            f"Expected the canonical schema: {CANONICAL_SCHEMA}")
    if not isinstance(raw, list):
        raise InventorySchemaError(
            f"{source}: 'symbols' is {type(raw).__name__}, not a list. "
            f"Expected the canonical schema: {CANONICAL_SCHEMA}")
    return raw


def symbols_by_language(inventory: dict, *,
                        source: str = "<in-memory inventory>") -> dict[str, list[dict]]:
    """Derived per-language grouping for the two former mapping readers.

    Derived on read, never stored on disk — the retired embedded per-language
    mapping is exactly the shape this module refuses (see ``symbols()`` above).
    """
    grouped: dict[str, list[dict]] = {}
    for sym in symbols(inventory, source=source):
        grouped.setdefault(sym.get("lang") or "unknown", []).append(sym)
    return grouped


def load(path, *, required: bool = True) -> dict | None:
    """Read and shape-validate an inventory artifact from *path*.

    ``required=True`` (the default): an absent path, or a present-but-unreadable
    one (I/O error / invalid JSON), raises ``InventorySchemaError``.
    ``required=False``: both of those degrade to ``None`` instead — the
    optional-input case (C-005).

    Either way, a artifact that IS readable but carries the wrong SHAPE always
    raises ``InventorySchemaError`` (D-2) — that check does not depend on
    ``required``, because a present-but-wrong-shaped artifact is a schema
    mismatch, not a missing input (AC-7).
    """
    p = Path(path)
    if not p.exists():
        if required:
            raise InventorySchemaError(f"{p}: inventory artifact not found")
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if not required:
            return None
        raise InventorySchemaError(f"{p}: unreadable inventory ({exc})") from exc
    symbols(data, source=str(p))          # present but wrong-shaped is ALWAYS loud,
    return data                           # regardless of `required` (AC-7, C-005)


def load_symbols(path, *, required: bool = True) -> list[dict] | None:
    """``load()`` + ``symbols()`` in one call. Returns ``None`` only when ``load()``
    itself degraded (``required=False`` on an absent/unreadable path); a loaded-but-
    wrong-shaped artifact still raises (``symbols()`` inside ``load()`` already
    enforces that)."""
    data = load(path, required=required)
    if data is None:
        return None
    return symbols(data, source=str(path))
