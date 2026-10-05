#!/usr/bin/env python3
"""prompt_honesty.py — mechanical honesty checker for core/agents/*.md (KLC-113).

Resolves every backticked `core/` | `scripts/` | `.klc/` | `docs/` reference,
every `` `klc <verb>` `` mention, and every
`` `python3 core/skills/<module>.py` `` mention named in the prompt tree,
against the real filesystem, the live `scripts/klc` verb set, or a
producer-backed allowlist for the runtime artifacts that never ship in git
(AC-6, AC-7, AC-8, AC-10).

Public entry point: ``scan(roots=None) -> list[str]``. An empty list means
the tree is honest. This is a real module (not test-only code) so an
operator can run it before committing, same shape as
`tests/test_docs_consolidation.py`'s pattern for docs (D-004).
"""
from __future__ import annotations

import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SKILLS_DIR.parent.parent
for _p in (str(_PROJECT_ROOT), str(_SKILLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.shared.paths import framework_root  # noqa: E402


@dataclass(frozen=True)
class AllowlistEntry:
    """One allowed reference. *pattern* is an fnmatch pattern (may carry a
    literal ``<KEY>``/``<TS>`` placeholder or a ``*``); *producer* names the
    file (optionally ``:line``) or ticket that writes the artifact — never
    empty, so a producer-less entry cannot be added silently (AC-8)."""
    pattern: str
    producer: str

    def __post_init__(self) -> None:
        if not self.producer.strip():
            raise ValueError(f"allowlist entry {self.pattern!r} names no producer")


# Runtime artifacts that never ship in git (`.klc/` is gitignored) or that a
# fresh checkout genuinely lacks, each with its real, named producer. Kept as
# EXACT literal paths, never a `.klc/config/*`-style wildcard — a wildcard
# would silently readmit a stripped reference such as `.klc/config/discovery.yml`
# (KLC-113 impl-plan-review F-1; D-005 strips that path specifically so it is
# NOT allowlisted).
ALLOWLIST: tuple[AllowlistEntry, ...] = (
    AllowlistEntry(".klc/index/inventory.json",             "scripts/update.py:261"),
    AllowlistEntry(".klc/index/inventory-hash.json",         "core/skills/per_module_hash.py"),
    AllowlistEntry(".klc/index/inventory-annotations.json",  "scripts/init.py:64 (inventory agent)"),
    AllowlistEntry(".klc/index/module_edges.json",           "scripts/update.py:261"),
    AllowlistEntry(".klc/index/symbol_usage.json",           "scripts/update.py:261"),
    AllowlistEntry(".klc/index/test_map.json",                "scripts/update.py:261"),
    AllowlistEntry(".klc/config/settings.yml",                "core/skills/settings.py"),
    AllowlistEntry(".klc/config/profile.yml",                 "core/skills/profile-resolve.py:56,64"),
    AllowlistEntry(".klc/tickets/*",                          "core/skills/artefacts.py"),
    AllowlistEntry(".klc/reports/*",                          "scripts/review.py"),
    AllowlistEntry(".klc/scratch/<KEY>/review/context.md",     "scripts/review.py (_write_shared_context)"),
    AllowlistEntry(".klc/scratch/<KEY>/retrieval_trace.json", "core/skills/planning-retriever.py (KLC-176 scratch trace)"),
    AllowlistEntry(".klc/scratch/<KEY>/build/*",               "core/skills/build_orchestrator.py (KLC-176 step files)"),
    AllowlistEntry(".klc/knowledge/*",                        "scripts/review.py:1104"),
    AllowlistEntry("docs/adr/*",                               "core/agents/docgen.md (ADR index)"),
    # KLC-113 review-fix (MEDIUM): narrowed from a `core/agents/review/*`
    # wildcard, which silently admitted ANY nonexistent path under that
    # directory (the same defect class impl-plan-review F-1 already fixed
    # for `.klc/config/*` above) — to the exact placeholder shape actually
    # referenced (retrospective.md's `core/agents/review/<reviewer>.md`).
    AllowlistEntry("core/agents/review/<reviewer>.md",         "config/reviewers.yml dispatches these by name"),
)

_PREFIXES = ("core/", "scripts/", ".klc/", "docs/")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_VERB_RE = re.compile(r"`klc ([a-z][a-z0-9-]*)")
_SKILL_INVOCATION_RE = re.compile(r"`python3 (core/skills/[A-Za-z0-9_.\-]+\.py)")


def _normalise(span: str) -> str:
    """First whitespace-delimited token only (drops CLI args and flags),
    then strip a trailing ``::symbol``, ``.symbol(``, or ``#fragment`` so
    ``module.fn(`` resolves against ``module.py`` and a doc anchor like
    ``docs/process.md#metrics`` resolves against ``docs/process.md``."""
    span = span.strip()
    if not span:
        return ""
    head = span.split()[0]
    head = head.split("::")[0]
    head = head.split("#")[0]
    if "(" in head:
        head = head.split("(")[0]
    return head.rstrip("/")


def _is_pattern(ref: str) -> bool:
    return "<" in ref or "*" in ref


def _allowed(ref: str) -> AllowlistEntry | None:
    for entry in ALLOWLIST:
        if fnmatch.fnmatch(ref, entry.pattern):
            return entry
    return None


def _module_file_exists(ref: str) -> bool:
    """True when *ref* names an existing path directly, or is
    ``<module-path>.<symbol>`` and ``<module-path>.py`` exists (the
    `module.symbol(` / `path::symbol(` normalisation the spec's AC-6
    describes)."""
    fw = framework_root()
    if (fw / ref).exists():
        return True
    if "." in ref:
        base, _, _tail = ref.rpartition(".")
        if base and (fw / f"{base}.py").exists():
            return True
    return False


def _prompt_files(roots: list[Path] | None = None) -> list[Path]:
    """Every prompt this checker scans. Defaults to `core/agents/*.md` PLUS
    `core/agents/review/*.md` (Q-003) — the sub-reviewer directory
    `generate_agents` itself does not descend into, but its prompts are
    dispatched by the review cascade all the same."""
    fw = framework_root()
    if roots is None:
        roots = [fw / "core" / "agents", fw / "core" / "agents" / "review"]
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.glob("*.md")))
        elif root.exists():
            files.append(root)
    return files


def klc_verbs(dispatcher: Path | None = None) -> set[str]:
    """The `klc` verb set, read live from `scripts/klc` (never re-declared
    here, per the ticket's assumption): the UNION of `LIFECYCLE_CMDS`,
    `OPERATIONAL_CMDS`, and the verbs served by an explicit `if cmd ==
    "<verb>":` handler (D-007 — `reindex`/`metrics`/`jira-sync` are
    deliberately absent from the two tuples)."""
    if dispatcher is None:
        dispatcher = framework_root() / "scripts" / "klc"
    text = dispatcher.read_text(encoding="utf-8")
    verbs: set[str] = set()
    for tup_name in ("LIFECYCLE_CMDS", "OPERATIONAL_CMDS"):
        m = re.search(rf"{tup_name}\s*=\s*\(([\s\S]*?)\)\n", text)
        if m:
            verbs.update(re.findall(r'"([a-z][a-z0-9-]*)"', m.group(1)))
    # KLC-177: the `klc internal` names stay callable. The DEPRECATED aliases
    # (ack, next, ship, jump, abort, run) are deliberately NOT accepted: they still
    # run for a while, but a prompt must teach `klc go` / `klc back`.
    m = re.search(r"INTERNAL_CMDS\s*=\s*\(([\s\S]*?)\)\n", text)
    if m:
        verbs.update(re.findall(r'"([a-z][a-z0-9-]*)"', m.group(1)))
    m = re.search(r"DEPRECATED\s*=\s*\{([\s\S]*?)\}\n", text)
    if m:
        verbs -= set(re.findall(r'"([a-z][a-z0-9-]*)"\s*:', m.group(1)))
    for m in re.finditer(r'if cmd == "([a-z][a-z0-9-]*)"', text):
        verbs.add(m.group(1))
    return verbs


def _bad_verbs(md: Path, text: str, verbs: set[str]) -> list[str]:
    return [
        f"{md.name}: unknown klc verb {m.group(1)!r}"
        for m in _VERB_RE.finditer(text)
        if m.group(1) not in verbs
    ]


def _bad_skill_invocations(md: Path, text: str) -> list[str]:
    fw = framework_root()
    return [
        f"{md.name}: skill invocation target does not exist {rel!r}"
        for rel in _SKILL_INVOCATION_RE.findall(text)
        if not (fw / rel).exists()
    ]


def scan(roots: list[Path] | None = None) -> list[str]:
    """Every unresolved reference in the prompt tree; `[]` means honest."""
    misses: list[str] = []
    verbs = klc_verbs()
    for md in _prompt_files(roots):
        text = md.read_text(encoding="utf-8")
        for span in _BACKTICK_RE.findall(text):
            ref = _normalise(span)
            if not ref or not ref.startswith(_PREFIXES):
                continue
            if _is_pattern(ref):
                if _allowed(ref) is not None:
                    continue
                misses.append(f"{md.name}: unresolved reference {ref!r}")
                continue
            if _module_file_exists(ref) or _allowed(ref) is not None:
                continue
            misses.append(f"{md.name}: unresolved reference {ref!r}")
        misses += _bad_verbs(md, text, verbs)
        misses += _bad_skill_invocations(md, text)
    return sorted(misses)


def main(argv: list[str] | None = None) -> int:
    misses = scan()
    if misses:
        print("prompt dishonesty detected:")
        for m in misses:
            print(f"  {m}")
        return 1
    print("prompt-honesty scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
