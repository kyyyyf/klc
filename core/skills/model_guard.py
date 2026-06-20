#!/usr/bin/env python3
"""model_guard.py — role-based MODEL_MISMATCH guard for the CC plugin.

check(phase, track, session_model) returns:
  - None           : ranks match, no warning needed
  - str (message)  : symmetric mismatch warning (role names, not model names)
  - str (soft note): session model unknown → cannot determine rank

The guard is role-based and abstract: the comparison uses `rank` from
models.yml, so a role pointing above Opus works unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

_skills_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_skills_dir))

import models as _m


def check_subagent_dispatch(resolved: "_m.ResolvedModel",
                            *, context: str = "subagent") -> str | None:
    """Return a MODEL_NOTE if `resolved` fell back to defaults (no explicit mapping).

    Returns None when the phase was explicitly mapped in per_track or phase_roles.
    """
    if getattr(resolved, "source", "default") == "default":
        return (
            f"MODEL_NOTE {context} phase={resolved.phase} "
            f"resolved={resolved.provider}:{resolved.model} "
            f"explicit-model-missing "
            f"(no per_track/phase_roles entry — using defaults)"
        )
    return None


def check(phase: str, *, track: str | None = None,
          session_model: str) -> str | None:
    """Return a mismatch warning or None.

    Args:
        phase:         Phase id (e.g. "discovery", "learn").
        track:         Ticket track (XS/S/M/L) for per-track role resolution.
        session_model: Concrete model name of the current CC session
                       (e.g. "claude-sonnet-4-6").

    Returns:
        None if ranks match or if session model is unknown (soft note
        returned as a string in the latter case when the model is
        completely unrecognised).
    """
    mc = _m.load_models()

    # Resolve required role for this phase.
    try:
        required = mc.resolve(phase, track=track)
    except (KeyError, ValueError):
        return None  # phase not in models.yml — no guard possible

    required_role = mc.roles.get(required.role)
    if required_role is None:
        return None
    required_rank = required_role.rank

    # Reverse-lookup: find which role the session_model belongs to.
    session_role_name: str | None = None
    session_rank: int | None = None
    for role_name, role in mc.roles.items():
        if role.model == session_model:
            session_role_name = role_name
            session_rank = role.rank
            break

    if session_role_name is None:
        # Unknown session model — soft note, no crash.
        return (
            f"[MODEL_MISMATCH] cannot determine role for session model "
            f"'{session_model}' — unable to verify rank against "
            f"required role '{required.role}' (rank {required_rank})."
        )

    if session_rank == required_rank:
        return None  # equal — silent

    if session_rank < required_rank:
        return (
            f"[MODEL_MISMATCH] session model is role '{session_role_name}' "
            f"(rank {session_rank}), but phase '{phase}' requires "
            f"'{required.role}' (rank {required_rank}) — consider /model "
            f"to a higher-rank model."
        )
    else:
        return (
            f"[MODEL_MISMATCH] session model is role '{session_role_name}' "
            f"(rank {session_rank}), but phase '{phase}' only requires "
            f"'{required.role}' (rank {required_rank}) — you may /model "
            f"down to a lower-rank model."
        )
