#!/usr/bin/env python3
"""gate.py — CC plugin hook that blocks advancing past a pick_required gate.

Called by hooks.json on UserPromptSubmit. Reads the JSON payload Claude Code
sends on stdin for the submitted `prompt`, reads KLC_TICKET from env, checks
the current phase via `klc status --json`, and exits 2 if the ticket is in
pick_required:ack-needed (blocking the user prompt until they pick explicitly
with `klc ack --pick N`).

The gate never holds KLC's own lifecycle commands. If the submitted prompt
invokes one of the gate-bypass-eligible verbs — ack, status, abort, jump,
step (the ones that resolve a pending choice or purely report state; run,
next, intake, publish and ship are deliberately excluded, since they mutate
phase state and bypassing the gate for them would defeat its purpose) — as a
single line, in any of the forms the operator actually types (`/klc:ack ...`,
the unprefixed project-skill form `/ack ...`, the bare CLI verb
`klc ack ...`, or the shell-mode form `!klc ack ...`), the gate exits 0 —
otherwise the operator would have no way to run the very `klc ack --pick N`
the block message asks for. A second line of instructions after the command
falls back to the normal rule. Setting the environment variable KLC_GATE=off
— before Claude Code starts, or via the settings `env` — disables the gate
entirely (documented escape hatch, also mentioned in the block message
itself); it has no effect if exported only after the block already appeared,
since hooks inherit the environment Claude Code itself was started with.

Exit codes (Claude Code UserPromptSubmit hook contract):
  0 — allow the prompt through; also every fail-open error path (missing
      ticket, failed `klc status`, missing framework root, unparseable or
      unreadable stdin, a framework lifecycle command, or KLC_GATE=off)
  2 — block; the message written to stderr is shown to the user
  any other non-zero code — a non-blocking hook error; the prompt still
      proceeds, and Claude Code's transcript shows a "<hook name> hook error"
      notice followed by the first line of the hook's stderr (that first line
      DOES reach the transcript — it is not hidden from the user)

The gate always exits 0 on any unexpected error (fail-open, C-002) and never
writes to stdout. It only acts when KLC_TICKET is exported by the caller;
nothing in this tree sets it today (follow-up KLC-161 covers deriving it
automatically instead of relying on the environment).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

STATUS_TIMEOUT_S = 5  # must stay below the gate's timeout in hooks.json (10 s)

# Matches the plugin's namespaced slash command ("/klc:ack ..."), the
# unprefixed project-skill form ("/ack ..."), the bare CLI verb
# ("klc ack ..."), and the shell-mode form ("!klc ack ...") — anchored at the
# start of the (stripped) prompt, so a prompt merely mentioning "klc ack"
# mid-sentence does not match (widened per external review LOW, KLC-153
# step-5, from the /klc:-only + no-! forms step-4 shipped).
_SLASH_COMMAND_RE = re.compile(r"^/(?:klc:)?([A-Za-z][\w-]*)\b")
_CLI_VERB_RE = re.compile(r"^!?\s*klc\s+([A-Za-z][\w-]*)\b")

# Fallback verb set used only if klc-plugin/commands/ cannot be read (e.g. a
# stripped-down install) — the escape hatch must stay available even then.
_FALLBACK_VERBS = {"ack", "status", "abort", "jump", "next", "ship", "step",
                    "intake", "publish", "run"}


def _lifecycle_verbs() -> set[str]:
    """Return the plugin's lifecycle verb names, derived from the shipped
    slash-command files under klc-plugin/commands/*.md, so this list never
    drifts from what the plugin actually registers. Falls back to a hardcoded
    set on any error."""
    try:
        commands_dir = Path(__file__).resolve().parent.parent / "commands"
        verbs = {p.stem for p in commands_dir.glob("*.md")}
        return verbs or _FALLBACK_VERBS
    except Exception:
        return _FALLBACK_VERBS


# Curated: only the verbs that resolve a pending gate choice or purely report
# state (external review LOW, KLC-153 step-5) — deliberately excludes run,
# next, intake, publish and ship, since those mutate phase state and
# bypassing the gate for them would defeat its purpose.
_GATE_BYPASS_CANDIDATES = frozenset({"ack", "status", "abort", "jump", "step"})


def _gate_bypass_verbs() -> set[str]:
    """Intersect the curated bypass policy with the plugin's real lifecycle
    verbs (_lifecycle_verbs), so a renamed/removed command file can't leave a
    stale verb exempted."""
    return _GATE_BYPASS_CANDIDATES & _lifecycle_verbs()


def _read_prompt_from_stdin() -> str | None:
    """Read and parse the UserPromptSubmit JSON payload from stdin.

    Returns the `prompt` string on success. Returns None if stdin cannot be
    read, is empty, is not valid JSON, or the JSON has no string `prompt`
    field — the caller then fails open (see main()), since an unparseable
    payload means the prompt's contents are unknown.
    """
    try:
        raw = sys.stdin.read()
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    prompt = payload.get("prompt")
    return prompt if isinstance(prompt, str) else None


def _is_framework_command(prompt: str) -> bool:
    """True if `prompt` invokes one of the gate-bypass-eligible lifecycle
    verbs (see _gate_bypass_verbs), as a single-line prompt, in any of the
    forms the operator actually types: the plugin's namespaced slash command
    (`/klc:ack ...`), the unprefixed project-skill form (`/ack ...`), the
    bare CLI verb (`klc ack ...`), or the shell-mode form (`!klc ack ...`).

    A prompt with a second line (e.g. "/klc:ack T --pick 1\\nnow implement
    X") is NOT exempt — the operator is doing more than just unblocking the
    gate, so the normal pick_required rule applies (external review LOW,
    KLC-153 step-5).
    """
    text = prompt.strip()
    if "\n" in text:
        return False
    match = _SLASH_COMMAND_RE.match(text) or _CLI_VERB_RE.match(text)
    return bool(match) and match.group(1) in _gate_bypass_verbs()


def _klc_status_json(ticket: str) -> dict | None:
    """Run `klc status <ticket> --json` and return parsed JSON or None on error."""
    import shlex
    klc_bin = os.environ.get("KLC_BIN", "klc")
    # KLC_BIN may be "python3 /path/to/klc" — split it into a list.
    klc_cmd = shlex.split(klc_bin) if " " in klc_bin else [klc_bin]
    try:
        result = subprocess.run(
            [*klc_cmd, "status", ticket, "--json"],
            capture_output=True, text=True, timeout=STATUS_TIMEOUT_S,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


def _phases_requiring_pick() -> set[str]:
    """Return phase ids that are pick_required.

    Loaded lazily so the hook has no import-time dependency on the
    framework being on PYTHONPATH.
    """
    fw_root = os.environ.get("KLC_FW_ROOT")
    if not fw_root:
        # Derive from this file's location: hooks/ → klc-plugin/ → fw_root
        fw_root = str(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))))

    try:
        sys.path.insert(0, os.path.join(fw_root, "core", "skills"))
        import phases as _ph
        ph = _ph.load_phases()
        return {p.id for p in ph.ordered if p.pick_required}
    except Exception:
        return set()


def _main_inner() -> int:
    if os.environ.get("KLC_GATE", "").strip().lower() == "off":
        return 0  # documented override — see module docstring

    prompt = _read_prompt_from_stdin()
    if prompt is None:
        return 0  # stdin unreadable/unparseable — fail open (C-002)
    if _is_framework_command(prompt):
        return 0  # never hold the framework's own lifecycle commands

    ticket = os.environ.get("KLC_TICKET", "").strip()
    if not ticket:
        return 0  # no ticket in context — allow

    status = _klc_status_json(ticket)
    if status is None:
        return 0  # can't determine state — allow (permissive)

    phase_id = status.get("phase_id", "")
    state = status.get("state", "")

    if state != "ack-needed":
        return 0  # not in ack-needed — allow

    pick_required_phases = _phases_requiring_pick()
    if phase_id not in pick_required_phases:
        return 0  # ack-needed but no pick required — allow

    # Block: ticket is in pick_required:ack-needed and no pick made yet.
    sys.stderr.write(
        f"[klc gate] Ticket {ticket} is in {phase_id}:ack-needed "
        f"(pick required).\n"
        f"Run: klc ack {ticket} --pick N\n"
        f"(use `klc status {ticket}` to see pick options)\n"
        f"(or restart Claude Code with KLC_GATE=off to disable this gate)\n"
    )
    return 2  # Claude Code blocks UserPromptSubmit only on exit 2 (C-001)


def main() -> int:
    try:
        return _main_inner()
    except Exception:
        return 0  # fail-open on any unexpected error (C-002)


if __name__ == "__main__":
    sys.exit(main())
