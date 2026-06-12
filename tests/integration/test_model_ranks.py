#!/usr/bin/env python3
"""Test that roles in models.yml carry a rank field with the expected ordering.

Covers:
  - heavy-reasoning.rank > coding.rank > local-simple.rank
  - roles sharing the same model share the same rank
  - rank is accessible via the Role dataclass (not a raw-dict read)
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import models as _m


def _load() -> _m.Models:
    _m._reset_cache()
    return _m.load_models(force=True)


def test_rank_ordering() -> None:
    """heavy-reasoning > coding > local-simple."""
    m = _load()
    hr = m.roles["heavy-reasoning"]
    cd = m.roles["coding"]
    ls = m.roles["local-simple"]
    assert hr.rank > cd.rank, (
        f"heavy-reasoning.rank ({hr.rank}) must be > coding.rank ({cd.rank})"
    )
    assert cd.rank > ls.rank, (
        f"coding.rank ({cd.rank}) must be > local-simple.rank ({ls.rank})"
    )


def test_shared_model_same_rank() -> None:
    """Roles sharing a concrete model must share a rank (no ambiguous reverse-lookup)."""
    m = _load()
    # Group roles by model string
    model_to_roles: dict[str, list[str]] = {}
    for name, role in m.roles.items():
        model_to_roles.setdefault(role.model, []).append(name)

    for model_name, role_names in model_to_roles.items():
        if len(role_names) < 2:
            continue
        ranks = {m.roles[n].rank for n in role_names}
        assert len(ranks) == 1, (
            f"Roles sharing model {model_name!r} have different ranks: "
            + ", ".join(f"{n}={m.roles[n].rank}" for n in role_names)
        )


def test_rank_attribute_on_role() -> None:
    """Role dataclass exposes .rank (not just raw dict) — guard can use it directly."""
    m = _load()
    for name, role in m.roles.items():
        assert hasattr(role, "rank"), f"Role {name!r} missing .rank attribute"
        assert isinstance(role.rank, int), (
            f"Role {name!r}.rank must be int, got {type(role.rank).__name__}"
        )
