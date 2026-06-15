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

import sys
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


def _cc_alias(model_id: str) -> str:
    return _MODEL_TO_CC_ALIAS.get(model_id, model_id)


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
        original = src.read_text(encoding="utf-8")
        dest.write_text(frontmatter + original, encoding="utf-8")
        generated.append(dest)

    return generated


_LIFECYCLE_CMDS = (
    "intake", "status", "next", "ack", "ship", "jump", "abort", "step",
)


def _generate_commands(output_dir: Path) -> list[Path]:
    """Write static command stubs (idempotent — skips existing files)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    verb_descriptions = {
        "intake": "Create a new klc ticket and start the lifecycle",
        "status": "Show current phase and track for a ticket",
        "next":   "Advance the ticket to the next work phase",
        "ack":    "Confirm phase work is done (optionally with --pick N)",
        "ship":   "Ack + next in one step",
        "jump":   "Jump the ticket to a specific phase",
        "abort":  "Cancel current work and return to the previous ack state",
        "step":   "Show or advance the current build step",
    }

    for verb in _LIFECYCLE_CMDS:
        dest = output_dir / f"{verb}.md"
        if dest.exists():
            generated.append(dest)
            continue
        desc = verb_descriptions.get(verb, f"Run klc {verb}")
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

    return generated


def main(argv: list[str] | None = None) -> int:
    fw = framework_root()
    plugin_dir = fw / "klc-plugin"
    agents_out = plugin_dir / "agents"
    commands_out = plugin_dir / "commands"

    generated_agents = generate_agents(output_dir=agents_out)
    print(f"Generated {len(generated_agents)} agent files in {agents_out}")

    generated_cmds = _generate_commands(output_dir=commands_out)
    print(f"Generated/verified {len(generated_cmds)} command files in {commands_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
