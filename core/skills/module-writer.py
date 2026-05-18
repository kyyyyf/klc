#!/usr/bin/env python3
"""module-writer.py — render CLAUDE.md files from Jinja2 templates.

Usage:
    module-writer.py --root [--out CLAUDE.md]
        Render the root CLAUDE.md from .klc/index/{inventory,modules}.json
        using framework/core/templates/CLAUDE.md.j2.

    module-writer.py --module <module-name> [--out <path>]
        Render one module's CLAUDE.md using framework/core/templates/module-CLAUDE.md.j2.
        Output path defaults to "<module.path>/CLAUDE.md".

    module-writer.py --all
        Render the root plus every module listed in modules.json.

The script is autonomous: it takes CLI arguments, emits results on stdout in
the form "WROTE <path>" one per line, and prints errors to stderr. Exit code
is 0 on full success, 1 otherwise. All text is English.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError:
    sys.stderr.write(
        "module-writer: jinja2 is required. Install with 'pip install jinja2' "
        "or 'uv pip install jinja2'.\n"
    )
    sys.exit(2)


MANUAL_BEGIN = "<!-- BEGIN: manual -->"
MANUAL_END = "<!-- END: manual -->"


def framework_root() -> Path:
    # Skill lives at core/skills/<file>.py; repo (= klc framework) is
    # three parents up.
    return Path(__file__).resolve().parent.parent.parent


def project_root() -> Path:
    env = os.environ.get("PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    return framework_root().parent


def klc_index_dir() -> Path:
    """Per-project index directory (see MIGRATION.md)."""
    return project_root() / ".klc" / "index"


def load_json(path: Path) -> dict:
    if not path.exists():
        sys.stderr.write(f"module-writer: missing file {path}\n")
        sys.exit(1)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(framework_root() / "core" / "templates")),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def extract_manual_block(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    m = re.search(
        re.escape(MANUAL_BEGIN) + r"(.*?)" + re.escape(MANUAL_END),
        text,
        flags=re.DOTALL,
    )
    return m.group(1).strip("\n") if m else ""


def collect_adr_index() -> list[dict]:
    adr_dir = project_root() / "docs" / "adr"
    if not adr_dir.exists():
        return []
    entries = []
    for p in sorted(adr_dir.glob("ADR-*.md")):
        title = p.stem
        try:
            first_line = p.read_text(encoding="utf-8").splitlines()[0]
            if first_line.startswith("#"):
                title = first_line.lstrip("# ").strip()
        except OSError:
            pass
        entries.append({"file": str(p.relative_to(project_root())), "title": title})
    return entries


def adrs_mentioning(module_name: str, module_path: str) -> list[dict]:
    out = []
    for adr in collect_adr_index():
        full = project_root() / adr["file"]
        try:
            body = full.read_text(encoding="utf-8")
        except OSError:
            continue
        if module_name in body or module_path in body:
            out.append(adr)
    return out


def render_root(out_path: Path | None) -> Path:
    inv = load_json(klc_index_dir() / "inventory.json")
    mods = load_json(klc_index_dir() / "modules.json")
    env = jinja_env()
    tpl = env.get_template("CLAUDE.md.j2")

    # Infer project name from common manifests.
    name = project_root().name
    for manifest, key in (
        ("package.json", "name"),
        ("Cargo.toml", None),
        ("pyproject.toml", None),
    ):
        p = project_root() / manifest
        if not p.exists():
            continue
        try:
            if manifest == "package.json":
                name = json.loads(p.read_text(encoding="utf-8")).get("name", name)
            else:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if manifest == "Cargo.toml" and line.startswith("name"):
                        name = line.split("=", 1)[1].strip().strip('"')
                        break
                    if manifest == "pyproject.toml" and line.startswith("name"):
                        name = line.split("=", 1)[1].strip().strip('"')
                        break
        except (OSError, ValueError):
            pass
        break

    ctx = {
        "project_name": name,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "languages": sorted(
            inv.get("structural", {}).get("languages", {}).items(),
            key=lambda kv: -kv[1].get("lines", 0),
        ),
        "total_lines": inv.get("structural", {}).get("total_lines", 0),
        "total_files": inv.get("structural", {}).get("total_files", 0),
        "modules": mods.get("modules", []),
        "cycles": mods.get("cycles", []),
        "adr_index": collect_adr_index(),
        "notes": inv.get("notes", []) + mods.get("notes", []),
    }
    out = out_path or (project_root() / "CLAUDE.md")
    out.write_text(tpl.render(**ctx), encoding="utf-8")
    print(f"WROTE {out}")
    return out


def render_module(module: dict, out_path: Path | None = None) -> Path:
    env = jinja_env()
    tpl = env.get_template("module-CLAUDE.md.j2")
    mod_path = project_root() / module["path"]
    target = out_path or (mod_path / (module.get("doc_filename") or "CLAUDE.md"))
    manual = extract_manual_block(target)
    ctx = {
        "module": module,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manual_block": manual,
        "adrs": adrs_mentioning(module["name"], module["path"]),
    }
    if not mod_path.exists():
        sys.stderr.write(
            f"module-writer: module path {mod_path} does not exist; skipping\n"
        )
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tpl.render(**ctx), encoding="utf-8")
    print(f"WROTE {target}")
    return target


def _resolve_doc_filenames(modules: list[dict]) -> list[dict]:
    """Pick a unique CLAUDE.md filename for each module.

    When two modules share module.path (e.g. a C# Build.cs module and a
    Python helpers module both living under CrushDemo/Plugins/Foo/), we
    write the second one to CLAUDE.<language>.md instead of silently
    overwriting the first. The chosen filename is stored back on the
    module dict as `doc_filename` so future runs are stable and so the
    root CLAUDE.md can link to the correct file.
    """
    by_path: dict[str, list[dict]] = {}
    for m in modules:
        by_path.setdefault(m["path"], []).append(m)
    for path, group in by_path.items():
        if len(group) == 1:
            group[0]["doc_filename"] = group[0].get("doc_filename") or "CLAUDE.md"
            continue
        # Deterministic order: first module keeps CLAUDE.md; others get
        # CLAUDE.<language>.md (falling back to CLAUDE.<name-slug>.md if
        # two modules share both path AND language).
        group_sorted = sorted(group, key=lambda m: (m.get("language", ""), m["name"]))
        seen: set[str] = set()
        for idx, m in enumerate(group_sorted):
            if idx == 0:
                fname = "CLAUDE.md"
            else:
                lang = m.get("language") or "mod"
                fname = f"CLAUDE.{lang}.md"
                if fname in seen:
                    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", m["name"]).strip("-")
                    fname = f"CLAUDE.{slug}.md"
            seen.add(fname)
            m["doc_filename"] = fname
        sys.stderr.write(
            f"module-writer: path collision at {path!r}: "
            + ", ".join(f"{m['name']}->{m['doc_filename']}" for m in group_sorted)
            + "\n"
        )
    return modules


def _verify(modules: list[dict]) -> list[str]:
    """Run the verify step from docgen.md. Returns a list of error strings."""
    errors: list[str] = []
    for m in modules:
        target = project_root() / m["path"] / (m.get("doc_filename") or "CLAUDE.md")
        if not target.exists():
            errors.append(f"missing doc: {target}")
    root = (project_root() / "CLAUDE.md").read_text(encoding="utf-8") if (project_root() / "CLAUDE.md").exists() else ""
    for m in modules:
        if m["name"] not in root:
            errors.append(f"root CLAUDE.md does not mention module {m['name']!r}")
    adr_dir = project_root() / "docs" / "adr"
    if adr_dir.exists():
        for adr in adr_dir.glob("ADR-*.md"):
            rel = str(adr.relative_to(project_root()))
            cited = rel in root
            if not cited:
                for m in modules:
                    doc = project_root() / m["path"] / (m.get("doc_filename") or "CLAUDE.md")
                    if doc.exists() and rel in doc.read_text(encoding="utf-8"):
                        cited = True; break
            if not cited:
                errors.append(f"ADR {rel} is not referenced from root or any module CLAUDE.md")

    # Docgen invariant: module CLAUDE.md must list public API as names
    # only. If a rendered file slipped through with `(` or `→` inside
    # the ## Public API block, the template drifted (or a manual edit
    # pasted signatures). Either way the reader pays tokens for data
    # that belongs in Serena.
    for m in modules:
        doc = project_root() / m["path"] / (m.get("doc_filename") or "CLAUDE.md")
        if not doc.exists():
            continue
        lines = doc.read_text(encoding="utf-8").splitlines()
        in_api = False
        for ln in lines:
            if ln.startswith("## Public API"):
                in_api = True; continue
            if in_api and ln.startswith("## "):
                break
            if in_api and ln.startswith("- `"):
                # `- \`sym\` — ...` is fine; `- \`sym(args)\`` is not.
                # We only look inside the first backtick span, which is
                # where the symbol name sits.
                tick = ln.find("`")
                end = ln.find("`", tick + 1) if tick >= 0 else -1
                name = ln[tick + 1: end] if end > tick else ln
                if "(" in name or "→" in name or "->" in name:
                    errors.append(
                        f"{doc}: public_api entry looks like a signature: {ln.strip()!r} "
                        "(names only — see docgen.md 'No signatures' rule)"
                    )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Render CLAUDE.md files from templates.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--root", action="store_true", help="render root CLAUDE.md")
    g.add_argument("--module", help="module name from modules.json")
    g.add_argument("--all", action="store_true", help="render root + all modules")
    g.add_argument("--only",
                   help="comma-separated list of module names to render. "
                        "Root is always rendered with this mode so the "
                        "overview table stays current, but per-module "
                        "CLAUDE.md is touched only for the named set. Use "
                        "this from periodic updates (differential mode).")
    g.add_argument("--check", action="store_true",
                   help="dry-run: compare current CLAUDE.md hashes against "
                        "inventory-hash.json and exit 1 on drift")
    ap.add_argument("--out", help="explicit output path (overrides default)")
    args = ap.parse_args()

    out = Path(args.out) if args.out else None

    try:
        if args.root:
            render_root(out)
        elif args.module:
            mods = load_json(klc_index_dir() / "modules.json")
            match = next(
                (m for m in mods.get("modules", []) if m["name"] == args.module), None
            )
            if match is None:
                sys.stderr.write(f"module-writer: unknown module {args.module!r}\n")
                return 1
            render_module(match, out)
        elif args.all or args.only:
            mods = load_json(klc_index_dir() / "modules.json")
            resolved = _resolve_doc_filenames(list(mods.get("modules", [])))
            # Persist doc_filename choices so subsequent runs are stable and
            # the root CLAUDE.md can link to the right file.
            (klc_index_dir() / "modules.json").write_text(
                json.dumps({**mods, "modules": resolved}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            render_root(None)

            if args.all:
                targets = resolved
            else:
                wanted = {n.strip() for n in args.only.split(",") if n.strip()}
                unknown = wanted - {m["name"] for m in resolved}
                if unknown:
                    sys.stderr.write(
                        f"module-writer: --only names unknown to modules.json: "
                        f"{sorted(unknown)}\n"
                    )
                    return 1
                targets = [m for m in resolved if m["name"] in wanted]
                if not targets:
                    sys.stderr.write("module-writer: --only resolved to empty set\n")
                    return 1

            for m in targets:
                render_module(m)

            # Verification and inventory-hash refresh must see a consistent
            # state of the whole tree. --only does not widen this gate
            # deliberately: a periodic run that only touched 2 of 50
            # modules still sees 50 CLAUDE.md files on disk and validates
            # them all.
            errors = _verify(resolved)
            if errors:
                sys.stderr.write("module-writer: verify failed:\n")
                for e in errors:
                    sys.stderr.write(f"  - {e}\n")
                sys.stderr.write(
                    "module-writer: inventory-hash.json was NOT updated; "
                    "fix the above and re-run.\n"
                )
                return 1
            _write_inventory_hash()
        elif args.check:
            return _check_inventory_hash()
    except Exception as exc:
        sys.stderr.write(f"module-writer: {exc}\n")
        return 1
    return 0


def _inventory_hash_payload() -> dict:
    """Compute the deterministic signature of the current docgen output.

    Keys are kept minimal on purpose: we want to detect *meaningful* drift —
    file set under each module, symbol count per module — not formatting
    noise in the CLAUDE.md itself.
    """
    import hashlib
    inv = load_json(klc_index_dir() / "inventory.json")
    mods = load_json(klc_index_dir() / "modules.json")

    per_module = {}
    for m in mods.get("modules", []):
        per_module[m["name"]] = {
            "symbol_count": m.get("symbol_count", 0),
            "public_api_len": len(m.get("public_api", [])),
            "depends_on": sorted(m.get("depends_on", [])),
        }
    canonical = json.dumps(per_module, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "digest": digest,
        "per_module": per_module,
        "total_symbols": inv.get("symbols", {}),
    }


def _write_inventory_hash() -> None:
    hash_path = klc_index_dir() / "inventory-hash.json"
    payload = _inventory_hash_payload()
    hash_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"WROTE {hash_path}")


def _check_inventory_hash() -> int:
    hash_path = klc_index_dir() / "inventory-hash.json"
    if not hash_path.exists():
        sys.stderr.write(
            "module-writer: no inventory-hash.json yet. "
            "Run `module-writer.py --all` after the inventory + decompose "
            "agents to create one.\n"
        )
        return 1
    stored = load_json(hash_path)
    current = _inventory_hash_payload()
    if stored.get("digest") == current.get("digest"):
        print("OK: CLAUDE.md hierarchy is up to date.")
        return 0
    sys.stderr.write(
        "DRIFT: inventory/modules signatures have changed since the last "
        "docgen run. Re-run `module-writer.py --all` and review the diff.\n"
    )
    # Show which modules moved.
    stored_mods = stored.get("per_module", {})
    current_mods = current.get("per_module", {})
    for name in sorted(set(stored_mods) | set(current_mods)):
        if stored_mods.get(name) != current_mods.get(name):
            sys.stderr.write(f"  drift  {name}: {stored_mods.get(name)} -> {current_mods.get(name)}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
