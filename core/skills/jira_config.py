#!/usr/bin/env python3
"""jira_config.py — load and validate jira.yml for klc Jira integration.

Exports:
    JiraConfig   — typed config dataclass
    JiraConfigError — raised on invalid/missing config
    load(config_dir)  — load + validate, return JiraConfig

The legacy `sync.*` keys used by jira_sync.py are not validated here;
they are read by jira_sync.py directly. This module covers the new KLC-020+
integration keys only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
from core.shared.paths import framework_root, klc_config_dir  # noqa: E402


class JiraConfigError(ValueError):
    """Raised when jira.yml is missing required fields or invalid."""


@dataclass
class JiraConfig:
    enabled: bool
    mode: str                     # "mirror" | "managed"
    base_url: str
    project_key: str
    auth_env: str
    auth_user_env: str
    gitlab_base_url: str
    gitlab_branch: str            # resolved: from config or git
    gitlab_blob_url_tmpl: str
    klc_to_jira: dict[str, str]
    jira_to_klc: dict[str, list[str]]
    artifact_paths: dict[str, str]
    comment_links: bool
    managed_tickets: list[str]   # empty = all tickets in managed mode

    def is_managed_ticket(self, ticket: str) -> bool:
        """True if this ticket should use managed (interactive) mode."""
        if self.mode != "managed":
            return False
        return not self.managed_tickets or ticket in self.managed_tickets

    def artifact_link_url(self, relative_path: str) -> str:
        """Build a GitLab blob URL for an artefact relative path."""
        return self.gitlab_blob_url_tmpl.format(
            base_url=self.gitlab_base_url.rstrip("/"),
            branch=self.gitlab_branch,
            path=relative_path,
        )


def _detect_git_branch() -> str:
    """Return current git branch name, or 'main' on failure."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "main"


def load(config_dir: Path | None = None) -> JiraConfig:
    """Load and validate jira.yml. Raises JiraConfigError on invalid config.

    Resolution order: per-project .klc/config/jira.yml, then framework
    config/jira.yml. Per-project file deep-merges on top.
    """
    # Guard against core/shared/yaml.py shadowing pyyaml in sys.path.
    import sys as _sys
    _shared_yaml_path = str(_project_root / "core" / "shared")
    _inserted = _shared_yaml_path in _sys.path
    if _inserted:
        _sys.path.remove(_shared_yaml_path)
    try:
        import importlib as _il
        if "yaml" in _sys.modules and not hasattr(_sys.modules["yaml"], "safe_load"):
            del _sys.modules["yaml"]
        import yaml
        if not hasattr(yaml, "safe_load"):
            raise ImportError("pyyaml not available")
    except ImportError:
        raise JiraConfigError("pyyaml is required (pip install pyyaml)")
    finally:
        if _inserted and _shared_yaml_path not in _sys.path:
            _sys.path.insert(0, _shared_yaml_path)

    def _load_yaml(path: Path) -> dict:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _deep_merge(base: dict, override: dict) -> dict:
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = _deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    if config_dir is None:
        fw_cfg = framework_root() / "config" / "jira.yml"
        proj_cfg = klc_config_dir() / "jira.yml"
    else:
        fw_cfg = config_dir / "jira.yml"
        proj_cfg = Path("/dev/null")  # no per-project override in test

    cfg = _deep_merge(_load_yaml(fw_cfg), _load_yaml(proj_cfg))

    enabled = bool(cfg.get("enabled", False))
    mode = cfg.get("mode", "mirror")
    if mode not in ("mirror", "managed"):
        raise JiraConfigError(f"jira.yml: mode must be 'mirror' or 'managed', got {mode!r}")

    site = cfg.get("site") or {}
    base_url = site.get("base_url", "").strip()
    if not base_url:
        raise JiraConfigError("jira.yml: site.base_url is required")
    import urllib.parse as _up
    _parsed = _up.urlparse(base_url)
    if _parsed.scheme != "https" or not _parsed.hostname:
        raise JiraConfigError(
            f"jira.yml: site.base_url must use https and include a hostname "
            f"(got {base_url!r}). Sending auth tokens over HTTP is unsafe."
        )
    project_key = site.get("project_key", "").strip()
    auth_env = site.get("auth_env", "").strip()
    if not auth_env:
        raise JiraConfigError("jira.yml: site.auth_env is required")
    auth_user_env = site.get("auth_user_env", "").strip()

    gitlab = cfg.get("gitlab") or {}
    gitlab_base_url = gitlab.get("base_url", "").strip()
    gitlab_branch_cfg = gitlab.get("branch", "").strip()
    gitlab_branch = gitlab_branch_cfg if gitlab_branch_cfg else _detect_git_branch()
    blob_url_tmpl = gitlab.get("blob_url", "{base_url}/-/blob/{branch}/{path}").strip()
    for var in ("{base_url}", "{branch}", "{path}"):
        if var not in blob_url_tmpl:
            raise JiraConfigError(
                f"jira.yml: gitlab.blob_url template missing {var!r}; "
                f"got: {blob_url_tmpl!r}"
            )

    status_mapping = cfg.get("status_mapping") or {}
    klc_to_jira: dict[str, str] = status_mapping.get("klc_to_jira") or {}
    if not klc_to_jira:
        raise JiraConfigError("jira.yml: status_mapping.klc_to_jira is required")
    jira_to_klc_raw: dict = status_mapping.get("jira_to_klc") or {}
    if not jira_to_klc_raw:
        raise JiraConfigError("jira.yml: status_mapping.jira_to_klc is required")
    # Normalise values to list[str]
    jira_to_klc: dict[str, list[str]] = {}
    for status, phases in jira_to_klc_raw.items():
        if isinstance(phases, list):
            jira_to_klc[status] = [str(p) for p in phases]
        elif phases is None:
            jira_to_klc[status] = []
        else:
            jira_to_klc[status] = [str(phases)]

    artifacts_cfg = cfg.get("artifacts") or {}
    comment_links = bool(artifacts_cfg.get("comment_links", True))
    artifact_paths: dict[str, str] = artifacts_cfg.get("paths") or {}

    managed_raw = cfg.get("managed_tickets")
    if managed_raw is None:
        managed_tickets: list[str] = []
    elif isinstance(managed_raw, list):
        managed_tickets = [str(t) for t in managed_raw]
    else:
        raise JiraConfigError(
            f"jira.yml: managed_tickets must be a list of ticket keys, "
            f"got {type(managed_raw).__name__!r}. "
            f"Use [] for all tickets or [KEY-1, KEY-2] to restrict."
        )

    return JiraConfig(
        enabled=enabled,
        mode=mode,
        base_url=base_url.rstrip("/"),
        project_key=project_key,
        auth_env=auth_env,
        auth_user_env=auth_user_env,
        gitlab_base_url=gitlab_base_url,
        gitlab_branch=gitlab_branch,
        gitlab_blob_url_tmpl=blob_url_tmpl,
        klc_to_jira=klc_to_jira,
        jira_to_klc=jira_to_klc,
        artifact_paths=artifact_paths,
        comment_links=comment_links,
        managed_tickets=managed_tickets,
    )
