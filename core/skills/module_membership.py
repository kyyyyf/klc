"""module_membership.py — the single file→module resolver (KLC-066).

`file_to_module(path, modules_data)` is the ONE authority for "which module does
this file belong to?". Every membership consumer (public-api-filter, module_edges,
scope_delta, diff-modules, update, context-loader) routes through it, so there is
exactly one module set — the #1 risk `planning_indexer.md` names is a second,
divergent set seen only by part of the toolchain.

Resolution (structure, not a single name — a shared file legitimately belongs to
many modules and must not become an orphan in diff/scope/review):

    file_to_module(path) -> {
      primary_module,     # str | None   (None for shared / orphan)
      member_of,          # [str]        (every module the file belongs to)
      is_shared,          # bool         (primary_module is None and len(member_of) > 1)
      resolution_source,  # "files_override" | "longest_prefix" | "orphan"
    }

Algorithm (from planning_indexer.md §"Единый resolver"):
  1. files[path].primary_module = X set  -> primary=X, member_of=[X]+secondary,
     is_shared=False, source=files_override.
  2. files[path].member_of set with primary_module=None -> primary=None,
     member_of=<as given>, is_shared=(len>1), source=files_override.
  3. else longest-prefix over modules[].path -> primary=X, member_of=[X],
     is_shared=False, source=longest_prefix.
  4. else -> orphan (primary=None, member_of=[], is_shared=False).

The longest-prefix branch is **boundary-aware**, and — critically — a directory
module and a file-stem module need DIFFERENT rules (a raw `startswith` over-matches
one way, a strip-and-unify over-matches the other):

  - **Directory module** (path ends in `/`, e.g. `core/agents/`): the slash IS the
    boundary. It matches files under it (`path.startswith("core/agents/")`) or the
    bare directory itself, but NOT a sibling file that shares the stem
    (`core/agents.py` must not match).
  - **File-stem module** (no trailing slash, e.g. `core/skills/scope_delta` which
    owns `core/skills/scope_delta.py`): matches the file itself, a directory with
    that stem (`<path>/...`), or the stemmed file (`<path>.ext`) — but NOT a
    `<stem>-x` / `<stem>_x` sibling (`core/agents/review` must not swallow
    `core/agents/review-lite.md`).

A raw `path.startswith(module_path)` is NOT safe: it lets `review` swallow
`review-lite.md`, silently passing an out-of-scope edit through the
review/integrate scope guard. The migrated consumers (public-api-filter /
scope_delta / diff-modules / context-loader) previously used the raw form; routing
them through this resolver unifies them onto one module set AND fixes that latent
over-match — byte-identical to the old behaviour for every file over the live repo
EXCEPT the one `review-lite.md` over-match, which was the bug. This matches the
boundary reasoning in `modules_build.py`.
"""
from __future__ import annotations

from typing import Any


def file_to_module(path: str, modules_data: dict[str, Any]) -> dict[str, Any]:
    """Resolve *path* to its module membership structure. See module docstring."""
    files = modules_data.get("files") or {}
    entry = files.get(path)

    if isinstance(entry, dict):
        primary = entry.get("primary_module")
        if primary:
            secondary = [s for s in (entry.get("secondary_modules") or []) if s != primary]
            return {
                "primary_module": primary,
                "member_of": [primary] + secondary,
                "is_shared": False,
                "resolution_source": "files_override",
            }
        member = list(entry.get("member_of") or [])
        if primary is None and member:
            return {
                "primary_module": None,
                "member_of": member,
                "is_shared": len(member) > 1,
                "resolution_source": "files_override",
            }
        # An entry with neither a usable primary nor member_of falls through to
        # longest-prefix so a malformed override never strands the file.

    best_name: str | None = None
    best_len = -1
    for m in modules_data.get("modules", []):
        mpath = m.get("path") or ""
        if not mpath:
            continue
        # Boundary-aware longest-prefix. A raw `startswith` over-matches in BOTH
        # directions, so directory modules and file-stem modules need DIFFERENT
        # rules (do not strip-and-unify — that lets a dir `core/agents/` swallow
        # the sibling FILE `core/agents.py` via the extension branch).
        if mpath.endswith("/"):
            # Directory module: the trailing slash IS the boundary. Match files
            # under it, or the bare directory path itself. It must NOT match a
            # sibling file that merely shares the stem (core/agents.py).
            match = path.startswith(mpath) or path == mpath[:-1]
        else:
            # File-stem module (e.g. core/skills/scope_delta owns scope_delta.py):
            # match the file itself, a directory with that stem, or the stemmed
            # file (<path>.ext) — but NOT a `<stem>-x`/`<stem>_x` sibling
            # (core/agents/review must not swallow core/agents/review-lite.md).
            match = (
                path == mpath
                or path.startswith(mpath + "/")
                or path.startswith(mpath + ".")
            )
        if match and len(mpath) > best_len:
            best_len = len(mpath)
            best_name = m.get("name")

    if best_name is not None:
        return {
            "primary_module": best_name,
            "member_of": [best_name],
            "is_shared": False,
            "resolution_source": "longest_prefix",
        }

    return {
        "primary_module": None,
        "member_of": [],
        "is_shared": False,
        "resolution_source": "orphan",
    }


def primary_module(path: str, modules_data: dict[str, Any]) -> str | None:
    """Convenience: the primary module name (or None). Consumers that only need
    one module use this; buckets that must not strand shared files use
    ``file_to_module`` and read ``member_of`` / ``is_shared``."""
    return file_to_module(path, modules_data)["primary_module"]
