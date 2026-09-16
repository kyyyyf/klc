#!/usr/bin/env python3
"""plugin_gen.py — generate klc-plugin/agents/ from core/agents/*.md.

Reads each top-level .md file in core/agents/, resolves the model for the
corresponding phase from models.yml, and writes the file into the target
agents/ directory with a model: frontmatter block prepended.

Usage:
    python3 core/skills/plugin_gen.py           # writes into klc-plugin/agents/
    from plugin_gen import generate_agents       # callable from tests / klc verb
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

_skills_dir = Path(__file__).resolve().parent
_project_root = _skills_dir.parent.parent
sys.path.insert(0, str(_skills_dir))
sys.path.insert(0, str(_project_root))

import models as _m
from core.shared.paths import framework_root  # noqa: E402


# CC plugin model alias map: concrete model ID → CC frontmatter alias.
# A role pointing above Opus works — it will fall back to the full model ID.
_MODEL_TO_CC_ALIAS: dict[str, str] = {
    "claude-opus-4-8":           "opus",
    "claude-opus-4-7":           "opus",
    "claude-opus-4-6":           "opus",
    "claude-sonnet-4-6":         "sonnet",
    "claude-sonnet-4-5":         "sonnet",
    "claude-haiku-4-5-20251001": "haiku",
    "claude-haiku-4-5":          "haiku",
    "claude-haiku-3-5":          "haiku",
    "claude-fable-5":            "fable",
}


def cc_alias(model_id: str) -> str:
    return _MODEL_TO_CC_ALIAS.get(model_id, model_id)


# Back-compat: earlier callers used the private name.
_cc_alias = cc_alias


# ---------------------------------------------------------------------------
# Verb-dictionary (single source for skills + shared command descriptions).
#
# `VERB_SPECS` holds the {short, use_when} strings for the 8 PASSTHROUGH verbs.
# The strings are lifted VERBATIM from the current committed
# `klc-plugin/skills/<verb>/SKILL.md` (constraint C-003 — the generator
# reproduces the delivery layer byte-for-byte, it does not "improve" it).
#
# Three verb sets are kept DISTINCT because they genuinely differ:
#   * SKILL_VERBS    — skills are generated for exactly these (== VERB_SPECS).
#   * BESPOKE_SKILLS — handwritten skills (run, discuss-feature); never
#     generated, only presence-guarded (constraint C-001: no Python driver).
#   * command verbs  — `_LIFECYCLE_CMDS` (incl. command-only `publish`) + run.
# ---------------------------------------------------------------------------
VERB_SPECS: dict[str, dict[str, str]] = {
    "intake": {
        "short": "Create a new klc ticket and start the lifecycle",
        "use_when": "Use when the user wants to create or start a new klc ticket from a description.",
    },
    "status": {
        "short": "Show current phase and track for a ticket",
        "use_when": "Use when the user wants to check what phase or track a klc ticket is in.",
    },
    "next": {
        "short": "Advance the ticket to the next work phase",
        "use_when": "Use when the user wants to move a klc ticket forward to its next phase.",
    },
    "ack": {
        "short": "Confirm phase work is done (optionally with --pick N or --auto for gate-policy)",
        "use_when": "Use when the user wants to confirm/approve that the current phase work is done, optionally picking a gate option.",
    },
    "ship": {
        "short": "Ack + next in one step",
        "use_when": "Use when the user wants to acknowledge the current phase and advance in one step.",
    },
    "jump": {
        "short": "Jump the ticket to a specific phase",
        "use_when": "Use when the user wants to jump a klc ticket to a specific phase.",
    },
    "abort": {
        "short": "Cancel current work and return to the previous ack state",
        "use_when": "Use when the user wants to cancel the current klc work and return to the previous ack state.",
    },
    "step": {
        "short": "Show or advance the current build step",
        "use_when": "Use when the user wants to show or advance the current build step of a klc ticket.",
    },
}

SKILL_VERBS: set[str] = set(VERB_SPECS)
BESPOKE_SKILLS: set[str] = {"run", "discuss-feature"}

# The fixed passthrough SKILL.md template. Only {v}, {short}, {use_when} vary.
_SKILL_TMPL = (
    "---\n"
    "name: klc-{v}\n"
    "description: {short}. {use_when}\n"
    "argument-hint: <TICKET-ID> [options]\n"
    "allowed-tools: Bash\n"
    "---\n"
    "\n"
    "# /klc:{v} — {short}\n"
    "\n"
    "Run `klc {v} $ARGUMENTS` via Bash and show the result verbatim. This is a thin\n"
    "adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic\n"
    "is reimplemented here). Pass the ticket key and any options straight through; surface\n"
    "the CLI's phase/gate output, including any advisory or blocking lines, to the user.\n"
)


def generate_skills(output_dir: Path | None = None) -> list[Path]:
    """Generate the passthrough ``skills/<verb>/SKILL.md`` for each SKILL_VERBS
    verb, byte-exact to the committed delivery layer (C-003).

    Only SKILL_VERBS are emitted, so no ``skills/publish`` is produced and the
    bespoke skills (run, discuss-feature) are never overwritten (AC-3).

    Args:
        output_dir: Destination ``skills/`` directory. Defaults to
                    ``<fw_root>/klc-plugin/skills/``.

    Returns:
        List of generated ``SKILL.md`` paths.
    """
    if output_dir is None:
        output_dir = framework_root() / "klc-plugin" / "skills"
    written: list[Path] = []
    for v in sorted(SKILL_VERBS):
        d = output_dir / v
        d.mkdir(parents=True, exist_ok=True)
        spec = VERB_SPECS[v]
        dest = d / "SKILL.md"
        dest.write_text(_SKILL_TMPL.format(v=v, **spec), encoding="utf-8")
        written.append(dest)
    return written


# The static plugin manifest, lifted VERBATIM from the committed
# `klc-plugin/.claude-plugin/plugin.json` (C-003) — trailing newline included —
# so the manifest is regenerable, not handwritten-and-lost.
_MANIFEST = (
    "{\n"
    '  "name": "klc",\n'
    '  "displayName": "klc — ticket lifecycle",\n'
    '  "version": "0.1.0",\n'
    '  "description": "Thin adapter that wraps the klc CLI as native Claude Code slash commands, subagents, and skills. Drives a ticket through its lifecycle (intake → discovery → build → review → integrate → archive) with TDD-ordered, track-scaled gates. No MCP server — shells out to the klc binary via Bash.",\n'
    '  "keywords": ["klc", "ticket", "lifecycle", "tdd", "workflow", "orchestration"]\n'
    "}\n"
)


def generate_manifest(output_dir: Path | None = None) -> Path:
    """Write ``.claude-plugin/plugin.json`` from the ``_MANIFEST`` constant,
    byte-exact to the committed manifest (AC-2 / C-003).

    Args:
        output_dir: Destination ``.claude-plugin/`` directory. Defaults to
                    ``<fw_root>/klc-plugin/.claude-plugin/``.

    Returns:
        Path to the written ``plugin.json``.
    """
    if output_dir is None:
        output_dir = framework_root() / "klc-plugin" / ".claude-plugin"
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "plugin.json"
    dest.write_text(_MANIFEST, encoding="utf-8")
    return dest


# Line-anchored, non-recursive {{include:<name>}} directive (KLC-113, D-001).
# Anchored to a whole line so a prose mention of the syntax is never expanded
# (KLC-104 lesson: an unanchored marker regex matches the marker's own
# description in prose).
_INCLUDE_RE = re.compile(r"(?m)^[ \t]*\{\{include:([a-z0-9][a-z0-9\-]*)\}\}[ \t]*$")


def expand_includes(text: str, includes_dir: Path | None = None) -> str:
    """Substitute each line-anchored ``{{include:name}}`` directive with the body
    of ``<includes_dir>/<name>.md``. Non-recursive by design: a directive inside
    an include body is left as literal text (KLC-113, D-001) — this is a single
    substitution pass, not a template engine.

    Args:
        text: the source prompt text, before frontmatter is prepended.
        includes_dir: directory holding the include bodies. Defaults to
                      ``<fw_root>/core/agents/_includes``.

    Returns:
        *text* with every directive replaced by its include's body.

    Raises:
        ValueError: an unresolvable include name — raising loudly here is the
                    point; a missing include must never ship as a literal
                    directive string in a dispatched prompt.
    """
    if includes_dir is None:
        includes_dir = framework_root() / "core" / "agents" / "_includes"

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        src = includes_dir / f"{name}.md"
        if not src.exists():
            raise ValueError(
                f"plugin_gen: unknown include {name!r} (no such file: {src})"
            )
        return src.read_text(encoding="utf-8").rstrip("\n")

    return _INCLUDE_RE.sub(_sub, text)


def generate_agents(
    output_dir: Path | None = None,
    *,
    models_yml: Path | None = None,
) -> list[Path]:
    """Generate plugin agents from core/agents/*.md.

    Args:
        output_dir:  Destination directory. Defaults to
                     <fw_root>/klc-plugin/agents/.
        models_yml:  Override models.yml path (for testing). When set, the
                     models cache is reset and loaded from this file.

    Returns:
        List of generated file paths.
    """
    fw = framework_root()
    if output_dir is None:
        output_dir = fw / "klc-plugin" / "agents"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load models — optionally override yml path.
    if models_yml is not None:
        # Temporarily redirect the load path by monkey-patching _load_path.
        _m._reset_cache()
        orig_load_path = _m._load_path

        def _patched_load_path() -> Path:
            return models_yml

        _m._load_path = _patched_load_path
        try:
            mc = _m.load_models(force=True)
        finally:
            _m._load_path = orig_load_path
            _m._reset_cache()
    else:
        mc = _m.load_models()

    agents_src = fw / "core" / "agents"
    generated: list[Path] = []

    for src in sorted(agents_src.glob("*.md")):
        phase_id = src.stem  # e.g. "discovery" from "discovery.md"
        # Resolve model for this phase; fall back to defaults.
        model_id: str = mc.defaults.model
        try:
            resolved = mc.resolve(phase_id)
            model_id = resolved.model
        except (KeyError, ValueError):
            pass  # phase not in phase_roles — use defaults

        cc_model = _cc_alias(model_id)

        # Build frontmatter.
        fm_lines = [
            "---",
            f"name: klc-{phase_id}",
            f"description: klc {phase_id} phase agent",
            f"model: {cc_model}",
            "---",
            "",
        ]
        frontmatter = "\n".join(fm_lines)

        dest = output_dir / src.name
        original = expand_includes(src.read_text(encoding="utf-8"))
        dest.write_text(frontmatter + original, encoding="utf-8")
        generated.append(dest)

    return generated


_LIFECYCLE_CMDS = (
    "intake", "status", "next", "ack", "ship", "jump", "abort", "step",
    "publish",
)


# Command-only verbs (∉ VERB_SPECS): they have a command stub but no skill.
# Shared verbs read their description from VERB_SPECS[verb]["short"] instead
# (AC-4 single source), so reconciling VERB_SPECS also reconciles the command.
_COMMAND_ONLY_DESC = {
    "publish": "Publish the review verdict to the ticket's GitHub PR",
}


def _cmd_desc(verb: str) -> str:
    """Description for a command stub. Shared verbs are single-sourced from
    ``VERB_SPECS[verb]["short"]`` (AC-4); command-only verbs keep their own."""
    if verb in VERB_SPECS:
        return VERB_SPECS[verb]["short"]
    return _COMMAND_ONLY_DESC.get(verb, f"Run klc {verb}")


def _generate_commands(output_dir: Path) -> list[Path]:
    """Write static command stubs (idempotent — skips existing files)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    for verb in _LIFECYCLE_CMDS:
        dest = output_dir / f"{verb}.md"
        if dest.exists():
            generated.append(dest)
            continue
        desc = _cmd_desc(verb)
        content = (
            f"---\n"
            f"description: {desc}\n"
            f"argument-hint: <TICKET-ID> [options]\n"
            f"allowed-tools: [Bash]\n"
            f"---\n\n"
            f"Run `klc {verb} $ARGUMENTS` via Bash and show the result.\n"
        )
        dest.write_text(content, encoding="utf-8")
        generated.append(dest)

    # `run` is not a CLI passthrough — it's the prompt-driven orchestrator
    # loop (KLC-052, C-001: no Python driver). Point at the canonical
    # instructions in klc-plugin/skills/run/SKILL.md instead of duplicating
    # them here (single source of truth for the loop).
    run_dest = output_dir / "run.md"
    if not run_dest.exists():
        run_content = (
            "---\n"
            "description: Run a ticket through its lifecycle (orchestrator loop)\n"
            "argument-hint: <TICKET-ID>\n"
            "allowed-tools: [Bash, Task, AskUserQuestion]\n"
            "---\n\n"
            "Read `klc-plugin/skills/run/SKILL.md` and follow its orchestrator "
            "loop instructions for ticket `$ARGUMENTS`.\n"
        )
        run_dest.write_text(run_content, encoding="utf-8")
    generated.append(run_dest)

    return generated


# Staged-path prefixes that make the plugin drift-check in scope (AC-8).
_PLUGIN_SOURCE_AGENTS_PREFIX = "core/agents/"
_PLUGIN_SOURCE_GEN = "core/skills/plugin_gen.py"


def plugin_sources_staged(staged_paths: list[str]) -> bool:
    """True when the staged paths include a plugin SOURCE — either a
    ``core/agents/*`` prompt or ``core/skills/plugin_gen.py`` (the
    verb-dictionary lives there). Scopes the pre-commit gate (AC-8) so it never
    fires for an unrelated commit. Injectable for unit testing."""
    for p in staged_paths:
        if p.startswith(_PLUGIN_SOURCE_AGENTS_PREFIX) or p == _PLUGIN_SOURCE_GEN:
            return True
    return False


def _stub_description(md: Path) -> str | None:
    """The ``description:`` frontmatter value of a command stub, or ``None`` when
    no such line exists. Used by the CMD-DESC-DRIFT check (review LOW-2)."""
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    return None


def check_sync(committed_root: Path | None = None) -> list[str]:
    """Regenerate agents+skills+manifest into a throwaway temp dir and compare
    to the committed plugin tree, returning drift findings (AC-7).

    Read-only: it never writes to *committed_root* and never stages anything.
    *committed_root* is injectable (defaults to ``<fw_root>/klc-plugin``) so a
    mutated committed tree is testable (review F-2).

    Each finding is ``MISSING: <rel>`` (no committed copy), ``DRIFT: <rel>``
    (committed bytes differ from the regenerated bytes), or
    ``CMD-DESC-DRIFT: commands/<verb>.md`` (a shared verb's committed command
    stub description no longer equals ``VERB_SPECS[verb]["short"]`` — review
    LOW-2; command stubs are skip-if-exists so we ASSERT the description, we do
    not byte-regenerate them, D-001).
    """
    if committed_root is None:
        committed_root = framework_root() / "klc-plugin"
    findings: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        generate_agents(output_dir=t / "agents")
        generate_skills(output_dir=t / "skills")
        generate_manifest(output_dir=t / ".claude-plugin")

        # agents — byte-exact
        for gen in sorted((t / "agents").glob("*.md")):
            dst = committed_root / "agents" / gen.name
            rel = f"agents/{gen.name}"
            if not dst.exists():
                findings.append(f"MISSING: {rel}")
            elif dst.read_bytes() != gen.read_bytes():
                findings.append(f"DRIFT: {rel}")

        # skills — byte-exact (SKILL_VERBS only)
        for v in sorted(SKILL_VERBS):
            gen = t / "skills" / v / "SKILL.md"
            dst = committed_root / "skills" / v / "SKILL.md"
            rel = f"skills/{v}/SKILL.md"
            if not dst.exists():
                findings.append(f"MISSING: {rel}")
            elif dst.read_bytes() != gen.read_bytes():
                findings.append(f"DRIFT: {rel}")

        # manifest — byte-exact
        gen = t / ".claude-plugin" / "plugin.json"
        dst = committed_root / ".claude-plugin" / "plugin.json"
        rel = ".claude-plugin/plugin.json"
        if not dst.exists():
            findings.append(f"MISSING: {rel}")
        elif dst.read_bytes() != gen.read_bytes():
            findings.append(f"DRIFT: {rel}")

    # command-description drift — a shared verb (∈ SKILL_VERBS) whose committed
    # commands/<verb>.md exists but whose description no longer matches the
    # single source VERB_SPECS[verb]["short"] (review LOW-2). Bring the offline
    # drift-guard assertion into the commit-time gate. We assert equality only
    # (no byte regeneration of command stubs — D-001).
    for v in sorted(SKILL_VERBS):
        cmd = committed_root / "commands" / f"{v}.md"
        if not cmd.exists():
            continue
        if _stub_description(cmd) != VERB_SPECS[v]["short"]:
            findings.append(f"CMD-DESC-DRIFT: commands/{v}.md")

    return findings


def _staged_paths() -> list[str]:
    """Paths staged for the current commit (``git diff --cached --name-only``),
    filtered to added/copied/modified. An injectable seam so ``--check-if-staged``
    is unit-testable without a real index (review LOW-1). Runs in the process
    cwd — i.e. the repo the pre-commit hook is firing in."""
    import subprocess

    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [line for line in out.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    argv = [] if argv is None else argv

    if "--check" in argv:
        findings = check_sync()
        if findings:
            print("plugin drift detected — the committed plugin is stale:")
            for f in findings:
                print(f"  {f}")
            print("run: python3 core/skills/plugin_gen.py")
            return 1
        return 0

    if "--check-if-staged" in argv:
        # The REAL hook gate (review LOW-1): scope with the same predicate the
        # tests exercise, so the hook and the unit test share one definition of
        # "in scope" — no grep re-implementation in bash.
        staged = _staged_paths()
        if not plugin_sources_staged(staged):
            return 0  # no plugin source staged — nothing to check
        findings = check_sync()
        if findings:
            print("plugin drift detected — the committed plugin is stale:")
            for f in findings:
                print(f"  {f}")
            print("run: python3 core/skills/plugin_gen.py")
            return 1
        return 0

    fw = framework_root()
    plugin_dir = fw / "klc-plugin"
    agents_out = plugin_dir / "agents"
    commands_out = plugin_dir / "commands"
    skills_out = plugin_dir / "skills"

    generated_agents = generate_agents(output_dir=agents_out)
    print(f"Generated {len(generated_agents)} agent files in {agents_out}")

    generated_cmds = _generate_commands(output_dir=commands_out)
    print(f"Generated/verified {len(generated_cmds)} command files in {commands_out}")

    generated_skills = generate_skills(output_dir=skills_out)
    print(f"Generated {len(generated_skills)} skill files in {skills_out}")

    manifest = generate_manifest(output_dir=plugin_dir / ".claude-plugin")
    print(f"Generated manifest {manifest}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
