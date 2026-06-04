#!/usr/bin/env python3
"""models.py — data-driven model selection over config/models.yml.

Analogous to core/skills/phases.py. Exposes a loader and a resolver
so host-side runners can ask `which model runs at phase X on track
Y?` without knowing the file's shape.

Project override: `.klc/config/models.yml` shadows the framework copy
when present.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
from core.shared.paths import framework_root, klc_config_dir  # noqa: E402
from core.shared.yaml import parse as _yaml_parse  # noqa: E402


KNOWN_PROVIDERS = ("anthropic", "openai", "ollama", "google")


# --- data classes ------------------------------------------------------------

_SENTINEL_UNSET = object()


@dataclass
class Role:
    name:        str
    provider:    str
    model:       str
    # api_key_env: explicit None = role needs no api key; _SENTINEL_UNSET
    # = defer to defaults. Strings carry the env var name.
    api_key_env: object = _SENTINEL_UNSET
    extra_args:  list[str] = field(default_factory=list)


@dataclass
class ResolvedModel:
    """What the runner needs to dispatch one agent call."""
    role:        str            # role-slot name ("coding", "heavy-reasoning")
    phase:       str            # phase id that asked for this model
    track:       str | None     # XS/S/M/L or None
    provider:    str
    model:       str
    api_key_env: str | None
    extra_args:  list[str]

    def as_env(self) -> dict[str, str]:
        """Env vars the runner passes to its child process. Names are
        stable so CI / hook scripts can grep them."""
        out = {
            "KLC_MODEL_ROLE":     self.role,
            "KLC_MODEL_PHASE":    self.phase,
            "KLC_MODEL_PROVIDER": self.provider,
            "KLC_MODEL_NAME":     self.model,
        }
        if self.track:
            out["KLC_MODEL_TRACK"] = self.track
        if self.api_key_env:
            out["KLC_MODEL_API_KEY_ENV"] = self.api_key_env
        return out


@dataclass
class Models:
    defaults:    Role
    roles:       dict[str, Role]
    phase_roles: dict[str, str]
    per_track:   dict[str, dict[str, str]]

    def resolve_role(self, role_name: str) -> ResolvedModel:
        """Return a ResolvedModel for a named role directly (not via phase lookup).

        Use this for fallback scenarios where the role name is known explicitly,
        avoiding coupling to pseudo-phase names like 'indexing'.
        """
        role = self.roles.get(role_name)
        if role is None:
            raise KeyError(
                f"models.yml: role {role_name!r} not defined under roles"
            )
        provider    = role.provider    or self.defaults.provider
        model       = role.model       or self.defaults.model
        if role.api_key_env is _SENTINEL_UNSET:
            api_key_env = self.defaults.api_key_env
        else:
            api_key_env = role.api_key_env
        if api_key_env is _SENTINEL_UNSET:
            api_key_env = None
        extra_args  = list(role.extra_args or self.defaults.extra_args)
        return ResolvedModel(
            role=role.name,
            phase=role_name,
            track=None,
            provider=provider,
            model=model,
            api_key_env=api_key_env,
            extra_args=extra_args,
        )

    def resolve(self, phase_id: str, *, track: str | None = None) -> ResolvedModel:
        """Return the ResolvedModel for `phase_id` on the given track."""
        role_name: str | None = None
        if track and track in self.per_track:
            role_name = self.per_track[track].get(phase_id)
        if role_name is None:
            role_name = self.phase_roles.get(phase_id)
        if role_name is None:
            raise KeyError(
                f"models.yml has no phase_roles[{phase_id!r}]; add it or "
                "set it under per_track[<track>] for this flow"
            )
        role = self.roles.get(role_name)
        if role is None:
            # Accept inline references like "anthropic:claude-opus-4-5"
            # as a future extension; for now require a named role.
            raise KeyError(
                f"models.yml: phase {phase_id!r} references role "
                f"{role_name!r} which is not defined under roles"
            )
        # Merge with defaults for missing fields.
        provider    = role.provider    or self.defaults.provider
        model       = role.model       or self.defaults.model
        if role.api_key_env is _SENTINEL_UNSET:
            api_key_env = self.defaults.api_key_env
        else:
            api_key_env = role.api_key_env
        if api_key_env is _SENTINEL_UNSET:
            api_key_env = None
        extra_args  = list(role.extra_args or self.defaults.extra_args)
        if provider not in KNOWN_PROVIDERS:
            raise ValueError(
                f"models.yml: role {role.name!r} uses unknown provider "
                f"{provider!r}; supported: {', '.join(KNOWN_PROVIDERS)}"
            )
        return ResolvedModel(
            role=role.name,
            phase=phase_id,
            track=track,
            provider=provider,
            model=model,
            api_key_env=api_key_env,
            extra_args=extra_args,
        )


# --- parsing ------------------------------------------------------------------

def _build_role(name: str, raw: dict) -> Role:
    if not isinstance(raw, dict):
        raise ValueError(f"models.yml: role {name!r} must be a mapping")
    provider    = raw.get("provider") or ""
    model       = raw.get("model") or ""
    # Distinguish "key not present" (defer to defaults) from
    # "present and null" (role explicitly needs no API key).
    if "api_key_env" in raw:
        api_key_env: object = raw["api_key_env"]
        if api_key_env is not None and not isinstance(api_key_env, str):
            raise ValueError(
                f"models.yml: role {name!r} api_key_env must be a string or null"
            )
    else:
        api_key_env = _SENTINEL_UNSET
    extra_args = raw.get("extra_args") or []
    if not isinstance(extra_args, list):
        raise ValueError(f"models.yml: role {name!r} extra_args must be a list")
    return Role(
        name=name,
        provider=str(provider),
        model=str(model),
        api_key_env=api_key_env,
        extra_args=[str(a) for a in extra_args],
    )


def _load_path() -> Path:
    """Project override wins over framework copy."""
    project_override = klc_config_dir() / "models.yml"
    if project_override.exists():
        return project_override
    fw_copy = framework_root() / "config" / "models.yml"
    if not fw_copy.exists():
        raise FileNotFoundError(
            f"models.yml not found at {project_override} or {fw_copy}"
        )
    return fw_copy


_CACHE: Models | None = None


def load_models(force: bool = False) -> Models:
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    path = _load_path()
    raw = _yaml_parse(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("models.yml: expected top-level mapping")

    defaults_raw = raw.get("defaults") or {}
    if not isinstance(defaults_raw, dict):
        raise ValueError("models.yml: defaults must be a mapping")
    defaults = _build_role("defaults", defaults_raw)
    if not defaults.provider:
        raise ValueError("models.yml: defaults.provider is required")
    if not defaults.model:
        raise ValueError("models.yml: defaults.model is required")

    roles_raw = raw.get("roles") or {}
    if not isinstance(roles_raw, dict):
        raise ValueError("models.yml: roles must be a mapping")
    roles = {name: _build_role(name, body) for name, body in roles_raw.items()}

    phase_roles_raw = raw.get("phase_roles") or {}
    if not isinstance(phase_roles_raw, dict):
        raise ValueError("models.yml: phase_roles must be a mapping")
    phase_roles = {str(k): str(v) for k, v in phase_roles_raw.items()}
    # Validate every phase_role value names a defined role.
    for phase, role_name in phase_roles.items():
        if role_name not in roles:
            raise ValueError(
                f"models.yml: phase_roles[{phase!r}] references undefined "
                f"role {role_name!r}"
            )

    per_track_raw = raw.get("per_track") or {}
    if not isinstance(per_track_raw, dict):
        raise ValueError("models.yml: per_track must be a mapping")
    per_track: dict[str, dict[str, str]] = {}
    for track, overrides in per_track_raw.items():
        if not isinstance(overrides, dict):
            raise ValueError(
                f"models.yml: per_track[{track!r}] must be a mapping"
            )
        per_track[str(track)] = {
            str(k): str(v) for k, v in overrides.items()
        }
        for phase, role_name in per_track[str(track)].items():
            if role_name not in roles:
                raise ValueError(
                    f"models.yml: per_track[{track!r}][{phase!r}] references "
                    f"undefined role {role_name!r}"
                )

    _CACHE = Models(
        defaults=defaults,
        roles=roles,
        phase_roles=phase_roles,
        per_track=per_track,
    )
    return _CACHE


def _reset_cache() -> None:
    """Test helper."""
    global _CACHE
    _CACHE = None


# --- CLI ---------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description="Inspect models.yml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="dump loaded roles + phase_roles as JSON")

    p_resolve = sub.add_parser("resolve", help="resolve model for (phase, track)")
    p_resolve.add_argument("--phase", required=True)
    p_resolve.add_argument("--track", default=None, choices=("XS", "S", "M", "L"))

    args = ap.parse_args(argv)
    try:
        m = load_models()
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"models: {e}\n")
        return 2

    if args.cmd == "list":
        print(_json.dumps({
            "defaults":     {"provider": m.defaults.provider,
                             "model":    m.defaults.model,
                             "api_key_env": m.defaults.api_key_env},
            "roles":        {k: {"provider": r.provider, "model": r.model,
                                  "api_key_env": r.api_key_env}
                             for k, r in m.roles.items()},
            "phase_roles":  m.phase_roles,
            "per_track":    m.per_track,
        }, indent=2))
        return 0

    if args.cmd == "resolve":
        try:
            r = m.resolve(args.phase, track=args.track)
        except (KeyError, ValueError) as e:
            sys.stderr.write(f"models: {e}\n")
            return 1
        print(_json.dumps({
            "role":        r.role,
            "phase":       r.phase,
            "track":       r.track,
            "provider":    r.provider,
            "model":       r.model,
            "api_key_env": r.api_key_env,
            "extra_args":  r.extra_args,
            "env":         r.as_env(),
        }, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
