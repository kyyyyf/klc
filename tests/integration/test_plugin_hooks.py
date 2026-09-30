#!/usr/bin/env python3
"""Test that the gate hook script blocks advancing past pick_required gates (AC-5).

The hook reads ticket phase via `klc status --json` and blocks when the ticket
is in a pick_required:ack-needed state but no pick has been made.

step-4 (KLC-153 follow-up fixes from code review + external review): the gate
must not hold KLC's own lifecycle commands or KLC_GATE=off (AC-3); a missing
hook script must not itself block via the interpreter's own exit code (AC-6);
the contract checker must apply per-role stdout rules without ever leaking a
raw json.JSONDecodeError (AC-6); the documented additionalContext/
sessionTitle keys are allowed (AC-6); several error paths that used to escape
as an uncaught exception (exit 1) must fail open (exit 0, AC-3); the gate
docstring wording is corrected further (AC-7); and `klc status` must not drain
the Jira queue (AC-8).
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_DIR = FW_ROOT / "klc-plugin"
HOOK_GATE = PLUGIN_DIR / "hooks" / "gate.py"
HOOK_REMIND = PLUGIN_DIR / "hooks" / "remind.py"
SCRIPTS = FW_ROOT / "scripts"
KLC = SCRIPTS / "klc"

# Claude Code's documented UserPromptSubmit hook contract (C-001): only exit 2,
# or JSON stdout with "decision": "block", blocks the prompt. Every other exit
# code is a non-blocking error. Plain stdout becomes context for Claude, not a
# user-facing message. additionalContext/sessionTitle added step-4 (external
# review LOW finding): both are documented UserPromptSubmit output fields too.
USER_PROMPT_SUBMIT_KEYS = {"decision", "reason", "continue", "stopReason",
                           "systemMessage", "suppressOutput", "hookSpecificOutput",
                           "additionalContext", "sessionTitle"}
ALLOWED_EXIT = {"gate.py": {0, 2}, "remind.py": {0}, "heartbeat.py": {0}}

# A neutral prompt that is never mistaken for one of KLC's own lifecycle
# commands — the safe default stdin payload for every gate invocation that
# isn't specifically testing the stdin-driven escape hatches (step-4, AC-3).
_DEFAULT_PROMPT = "what should I work on next? (an ordinary chat message)"


def _prompt_json(prompt: str) -> str:
    """Build the UserPromptSubmit stdin JSON payload for a given prompt text."""
    return json.dumps({"prompt": prompt})


def _make_env(project_root: Path) -> dict[str, str]:
    env = {**os.environ, "PROJECT_ROOT": str(project_root)}
    env.pop("KLC_TICKETS_DIR", None)
    # Point KLC_BIN at our scripts/klc so gate.py can call it without PATH deps.
    env["KLC_BIN"] = f"{sys.executable} {KLC}"
    env["KLC_FW_ROOT"] = str(FW_ROOT)
    return env


def _bootstrap_ticket(klc_dir: Path, ticket: str, phase: str,
                      track: str = "M", *, holder_id: str | None = None) -> None:
    import json as _j
    tdir = klc_dir / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "kind_source": "user",
        "phase": phase,
        "phase_history": [],
        "track": track,
        "affected_modules": [],
        "estimate": None,
        "jira_url": None,
        "created": "2026-01-01T00:00:00Z",
    }
    if holder_id is not None:
        # step-4: used by the remind-actually-fires fixture, mirroring
        # test_remind.py's _fabricate_ticket(holder_id=...).
        meta["holder"] = {"id": holder_id, "machine": "test-machine",
                          "since": "2026-01-01T00:00:00Z"}
    (tdir / "meta.json").write_text(_j.dumps(meta), encoding="utf-8")


def _git_init(path: Path, email: str) -> None:
    """Init a throwaway git repo with a fixed identity (mirrors
    tests/integration/test_remind.py::_git_init) — used so the remind hook's
    real `_git_user()` resolves a known identity, not the ambient one."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", email], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _run_gate(ticket: str | None, phase: str = "design:ack-needed",
              track: str = "M", *, klc_bin: str | None = None,
              fw_root: str | None = None,
              drop_pythonpath: bool = False,
              stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Bootstrap a temp PROJECT_ROOT (with `ticket`'s meta.json when given) and
    run gate.py as a subprocess, returning the completed process.

    `stdin` (step-4) is the raw text fed to the hook's stdin — the
    UserPromptSubmit JSON payload. Defaults to a valid JSON payload carrying
    an ordinary, non-framework prompt, so every existing blocking/allow test
    keeps exercising the pick_required logic exactly as before; pass an
    explicit `stdin` only to test the stdin-driven paths themselves.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        klc_dir = root / ".klc"
        klc_dir.mkdir()
        if ticket is not None:
            _bootstrap_ticket(klc_dir, ticket, phase=phase, track=track)

        env = _make_env(root)
        if ticket is not None:
            env["KLC_TICKET"] = ticket
        else:
            env.pop("KLC_TICKET", None)
        if klc_bin is not None:
            env["KLC_BIN"] = klc_bin
        if fw_root is not None:
            env["KLC_FW_ROOT"] = fw_root
        if drop_pythonpath:
            env.pop("PYTHONPATH", None)

        if stdin is None:
            stdin = _prompt_json(_DEFAULT_PROMPT)

        return subprocess.run(
            [sys.executable, str(HOOK_GATE)],
            capture_output=True, text=True, env=env, input=stdin,
        )


def _write_stub_klc(tmp_path: Path, stdout_text: str) -> str:
    """Write a tiny standalone script that ignores argv, writes `stdout_text`
    verbatim to stdout and exits 0 — used as KLC_BIN to feed gate.py a
    crafted (possibly malformed-for-gate) `klc status --json` response."""
    stub = tmp_path / "fake_klc.py"
    stub.write_text(
        "import sys\n"
        f"sys.stdout.write({stdout_text!r})\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {stub}"


def _load_hook_module(name: str):
    """Load a hooks/<name>.py script as an importable module, by path."""
    path = PLUGIN_DIR / "hooks" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_hook_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _hook_timeout(script_name: str) -> int:
    """Return the `timeout` hooks.json declares for the UserPromptSubmit
    entry whose command references `script_name`."""
    data = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    for group in data["hooks"]["UserPromptSubmit"]:
        for entry in group["hooks"]:
            if script_name in entry["command"]:
                return entry["timeout"]
    raise AssertionError(f"no hooks.json UserPromptSubmit entry references {script_name}")


def _registered_commands(hooks_json: Path) -> list[str]:
    """Return every UserPromptSubmit command string registered in hooks_json.

    Raises AssertionError if the file registers no commands at all — an
    empty contract is itself a contract violation (nothing would be checked).
    """
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    commands = [
        entry["command"]
        for group in data["hooks"]["UserPromptSubmit"]
        for entry in group["hooks"]
    ]
    assert commands, f"{hooks_json} registers no UserPromptSubmit commands"
    return commands


def _script_from_command(command: str) -> str:
    """Return which known hook role a hooks.json command string invokes,
    matched by the exact script filename immediately after a path separator
    (e.g. ".../hooks/gate.py") — not merely a keyword occurring anywhere in
    the command string (step-4, tightened per external review HIGH finding)."""
    for name in ALLOWED_EXIT:
        if re.search(rf"/{re.escape(name)}(['\"]|$)", command):
            return name
    raise AssertionError(f"no known hook role found in command: {command!r}")


def _run_hook_command(command: str, env: dict[str, str], *,
                      prompt: str = _DEFAULT_PROMPT) -> subprocess.CompletedProcess[str]:
    """Resolve ${CLAUDE_PLUGIN_ROOT} in a hooks.json command string and run it
    as a real subprocess (matching how Claude Code itself invokes it),
    feeding a valid UserPromptSubmit JSON payload on stdin so gate.py's
    stdin-parsing path never spuriously fails open just because no stdin was
    supplied (step-4)."""
    resolved = command.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_DIR))
    return subprocess.run(
        shlex.split(resolved), capture_output=True, text=True, env=env,
        input=_prompt_json(prompt),
    )


def _check_hook_result(script: str, returncode: int, stdout: str) -> None:
    """Assert a hook's actual (returncode, stdout) obeys the documented
    per-role contract. Raises AssertionError — never json.JSONDecodeError —
    on any violation (fail-closed).

    Per-role stdout rules (step-4, tightened per code-review MEDIUM +
    external-review MEDIUM findings):
      gate.py      — stdout must always be empty (it never emits context).
      heartbeat.py — stdout must always be empty (silent by contract).
      remind.py    — stdout may be empty, plain text (valid UserPromptSubmit
                     context per the docs — this is remind.py's real,
                     documented output shape, not JSON), or a JSON object
                     whose keys are all documented output fields.
    """
    assert script in ALLOWED_EXIT, f"unknown hook role: {script}"
    assert returncode in ALLOWED_EXIT[script], (script, returncode)
    text = stdout.strip()

    if script in ("gate.py", "heartbeat.py"):
        assert text == "", (script, stdout)
        return

    # remind.py: empty and plain text are both fine; only stdout SHAPED like a
    # JSON object (per the docs' "starts with { and ends with }" rule) is
    # held to the documented-keys check.
    if not text:
        return
    if text.startswith("{") and text.endswith("}"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"{script}: stdout looks like a JSON object but does not parse: {exc}"
            ) from exc
        assert isinstance(payload, dict), (script, text)
        assert set(payload) <= USER_PROMPT_SUBMIT_KEYS, (script, set(payload))
        return
    # Otherwise: plain text, valid UserPromptSubmit context. Nothing more to check.


def test_gate_hook_script_exists() -> None:
    """AC-6: hooks/gate.py exists in the plugin directory."""
    assert HOOK_GATE.exists(), (
        f"klc-plugin/hooks/gate.py missing — gate hook not implemented"
    )


def test_hooks_json_exists() -> None:
    """AC-6: hooks/hooks.json exists and is valid JSON."""
    hooks_json = PLUGIN_DIR / "hooks" / "hooks.json"
    assert hooks_json.exists(), "klc-plugin/hooks/hooks.json missing"
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "hooks.json must be a JSON object"
    assert "hooks" in data, "hooks.json must have a 'hooks' key"


def test_gate_block() -> None:
    """AC-5: a pick-required ack-needed ticket makes the gate exit exactly 2."""
    result = _run_gate("T-GATE-001", phase="design:ack-needed", track="M")
    assert result.returncode == 2, (
        "gate hook should block with exit code 2 for pick_required:ack-needed;\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert result.stdout == "", result.stdout


def test_gate_pass() -> None:
    """AC-2/AC-3: a non-blocking ticket exits 0 and keeps stdout empty."""
    result = _run_gate("T-GATE-002", phase="discovery-lite:work", track="S")
    assert result.returncode == 0, (
        "gate hook should pass (exit 0) for work state;\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert result.stdout == "", result.stdout


def test_gate_block_message_names_ticket_phase_and_command() -> None:
    """AC-4: the stderr block message names the ticket, the phase and the pick command."""
    result = _run_gate("T-GATE-003", phase="design:ack-needed", track="M")
    assert result.returncode == 2, result
    assert "T-GATE-003" in result.stderr, result.stderr
    assert "design" in result.stderr, result.stderr
    assert "klc ack T-GATE-003 --pick N" in result.stderr, result.stderr


def test_gate_allows_when_ticket_unset() -> None:
    """AC-3: pin — an unset KLC_TICKET fails open with exit 0 and empty stdout."""
    result = _run_gate(None)
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_when_status_fails() -> None:
    """AC-3: pin — a failing `klc status` fails open with exit 0, never 2."""
    result = _run_gate(
        "T-GATE-004", phase="design:ack-needed", track="M",
        klc_bin=f"{sys.executable} -c 'import sys; sys.exit(3)'",
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_when_framework_root_missing() -> None:
    """AC-3: pin — a missing framework root fails open with exit 0, never 2."""
    with tempfile.TemporaryDirectory() as empty_root:
        result = _run_gate(
            "T-GATE-005", phase="design:ack-needed", track="M",
            fw_root=empty_root, drop_pythonpath=True,
        )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_status_timeout_below_hook_timeout(monkeypatch) -> None:
    """AC-8: the inner klc status timeout is strictly below the hook timeout.

    step-4: gate.py now reads stdin first, so this in-process call must feed
    it a valid, non-lifecycle prompt on stdin — otherwise the new stdin-parse
    fail-open path would return 0 before ever reaching `_klc_status_json`,
    and the monkeypatched `subprocess.run` recorder below would never fire.
    """
    gate = _load_hook_module("gate")
    monkeypatch.setattr(sys, "stdin", io.StringIO(_prompt_json("ordinary status timeout probe")))
    seen: dict[str, object] = {}

    def _record(cmd, **kw):
        seen.update(kw)
        raise OSError("stub — no real subprocess is run")

    monkeypatch.setattr(gate.subprocess, "run", _record)
    monkeypatch.setenv("KLC_TICKET", "T-GATE-008")
    assert gate.main() == 0
    assert seen["timeout"] == gate.STATUS_TIMEOUT_S
    assert gate.STATUS_TIMEOUT_S < _hook_timeout("gate.py")


_EXPECTED_EXIT_BY_SCENARIO = {
    True:  {"gate.py": 2, "remind.py": 0, "heartbeat.py": 0},   # blocking ticket present
    False: {"gate.py": 0, "remind.py": 0, "heartbeat.py": 0},   # no ticket
}


def test_registered_hooks_follow_contract() -> None:
    """AC-6: pin — every hooks.json command obeys the documented exit/stdout
    contract, with the EXACT expected exit code pinned per scenario (step-4,
    tightened per external-review HIGH finding: the old version only checked
    membership in the allowed set, so a wrong-but-allowed code could pass
    unnoticed), and each command matched to its hook role by its exact script
    filename rather than a loose substring."""
    hooks_json = PLUGIN_DIR / "hooks" / "hooks.json"
    commands = _registered_commands(hooks_json)

    for with_blocking_ticket in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            klc_dir = root / ".klc"
            klc_dir.mkdir()
            env = _make_env(root)
            if with_blocking_ticket:
                _bootstrap_ticket(klc_dir, "T-GATE-006",
                                  phase="design:ack-needed", track="M")
                env["KLC_TICKET"] = "T-GATE-006"
            else:
                env.pop("KLC_TICKET", None)

            for command in commands:
                script = _script_from_command(command)
                result = _run_hook_command(command, env)
                expected = _EXPECTED_EXIT_BY_SCENARIO[with_blocking_ticket][script]
                assert result.returncode == expected, (
                    script, with_blocking_ticket, result
                )
                _check_hook_result(script, result.returncode, result.stdout)


def test_hook_launcher_exits_zero_when_script_missing() -> None:
    """AC-6: pin — the hooks.json launcher exits 0, not the raw interpreter's
    own exit-2-for-missing-file, when a registered command points at a script
    that does not exist (e.g. a stale plugin install). Verified directly:
    `python3 <missing-path>` exits 2, which Claude Code treats as a block."""
    hooks_json = PLUGIN_DIR / "hooks" / "hooks.json"
    commands = _registered_commands(hooks_json)
    gate_command = next(c for c in commands if _script_from_command(c) == "gate.py")
    missing_command = gate_command.replace("hooks/gate.py", "hooks/does-not-exist.py")

    result = _run_hook_command(missing_command, dict(os.environ))
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_contract_check_rejects_bad_output() -> None:
    """AC-6: pin — the contract checker is fail-closed on every violation shape."""
    with pytest.raises(AssertionError):
        _check_hook_result("gate.py", 1, "")  # 1 is not in {0, 2}
    with pytest.raises(AssertionError):
        _check_hook_result("gate.py", 0, json.dumps({"unknownKey": True}))
    with pytest.raises(AssertionError):
        _check_hook_result("gate.py", 0, json.dumps([1, 2, 3]))  # not a JSON object
    with pytest.raises(AssertionError):
        _check_hook_result("no-such-hook.py", 0, "")  # no documented role

    with tempfile.TemporaryDirectory() as tmp:
        empty_hooks_json = Path(tmp) / "hooks.json"
        empty_hooks_json.write_text(
            json.dumps({"hooks": {"UserPromptSubmit": []}}), encoding="utf-8",
        )
        with pytest.raises(AssertionError):
            _registered_commands(empty_hooks_json)


def test_check_hook_result_enforces_empty_stdout_for_gate_and_heartbeat() -> None:
    """AC-6: pin — gate.py and heartbeat.py must have exactly empty stdout;
    any non-empty output (even an otherwise well-formed JSON object) is
    rejected, since neither hook is documented to emit context."""
    with pytest.raises(AssertionError):
        _check_hook_result("gate.py", 0, json.dumps({"decision": "block"}))
    with pytest.raises(AssertionError):
        _check_hook_result("heartbeat.py", 0, "some text")
    _check_hook_result("gate.py", 2, "")       # empty is fine
    _check_hook_result("heartbeat.py", 0, "")  # empty is fine


def test_check_hook_result_allows_remind_plain_text_and_json() -> None:
    """AC-6: pin — remind.py's contract allows empty stdout, plain text (its
    real, documented UserPromptSubmit-context output shape — see F-005/Q-001),
    or a valid JSON object with documented keys."""
    _check_hook_result("remind.py", 0, "")
    _check_hook_result("remind.py", 0, "KLC-901 integrate is done — run klc ack\n")
    _check_hook_result("remind.py", 0, json.dumps({"systemMessage": "hi"}))
    with pytest.raises(AssertionError):
        _check_hook_result("remind.py", 0, json.dumps({"unknownKey": True}))


def test_check_hook_result_raises_assertion_error_not_json_decode_error() -> None:
    """AC-6: pin — stdout that merely LOOKS like a JSON object (braces, but
    invalid content) must raise AssertionError, never a raw
    json.JSONDecodeError, matching this function's own fail-closed contract."""
    with pytest.raises(AssertionError):
        _check_hook_result("remind.py", 0, "{not valid json}")


def test_user_prompt_submit_keys_include_additional_context_and_session_title() -> None:
    """AC-6: the documented UserPromptSubmit output fields additionalContext
    and sessionTitle (docs.claude.com hooks reference, read 2026-09-30) are
    part of the allowed key set, so a hook that correctly emits them is not
    penalised by the contract test (external-review LOW finding)."""
    assert "additionalContext" in USER_PROMPT_SUBMIT_KEYS
    assert "sessionTitle" in USER_PROMPT_SUBMIT_KEYS


def test_hook_docstrings_state_current_contract() -> None:
    """AC-7: hook docstrings state the current Claude Code exit-code contract,
    including the corrected wording (step-4, external-review LOW finding)
    that a non-2 non-zero exit still shows the hook's first stderr line in
    the transcript, and document the new KLC_GATE=off escape hatch."""
    gate_doc = ast.get_docstring(ast.parse(HOOK_GATE.read_text(encoding="utf-8")))
    remind_doc = ast.get_docstring(ast.parse(HOOK_REMIND.read_text(encoding="utf-8")))
    assert gate_doc is not None
    assert remind_doc is not None
    assert not re.search(r"(?im)^\s*1\s*[—-]\s*block", gate_doc), gate_doc
    assert re.search(r"(?i)\b2\b.*block", gate_doc), gate_doc
    assert "KLC_TICKET" in gate_doc, gate_doc
    assert "context" in remind_doc.lower(), remind_doc
    assert "KLC_GATE" in gate_doc, gate_doc
    assert not re.search(r"does not show the hook.s stderr", gate_doc, re.I), gate_doc
    assert re.search(r"(?i)first line", gate_doc), gate_doc


# --- step-4: the gate must not hold the framework's own commands (AC-3) -----


def test_gate_allows_slash_command_even_when_blocking() -> None:
    """AC-3: the plugin's own /klc:ack slash command is never held by the
    gate, even while the ticket sits in pick_required:ack-needed — otherwise
    the operator has no way to run the very command the block message asks
    for."""
    result = _run_gate(
        "T-GATE-013", phase="design:ack-needed", track="M",
        stdin=_prompt_json("/klc:ack T-GATE-013 --pick 1"),
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_status_slash_command_even_when_blocking() -> None:
    """AC-3: /klc:status is exempt too — the operator must be able to see the
    pick options the block message points them to."""
    result = _run_gate(
        "T-GATE-014", phase="design:ack-needed", track="M",
        stdin=_prompt_json("/klc:status T-GATE-014"),
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_cli_verb_form_even_when_blocking() -> None:
    """AC-3: the bare CLI form (`klc ack ...`, no leading slash) is exempt
    too, not just the plugin's own slash-command syntax."""
    result = _run_gate(
        "T-GATE-015", phase="design:ack-needed", track="M",
        stdin=_prompt_json("klc ack T-GATE-015 --pick 1"),
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_when_klc_gate_env_is_off() -> None:
    """AC-3: the documented KLC_GATE=off override disables the gate entirely,
    even for an otherwise-blocking ticket and an ordinary prompt."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        klc_dir = root / ".klc"
        klc_dir.mkdir()
        _bootstrap_ticket(klc_dir, "T-GATE-016", phase="design:ack-needed", track="M")
        env = _make_env(root)
        env["KLC_TICKET"] = "T-GATE-016"
        env["KLC_GATE"] = "off"
        result = subprocess.run(
            [sys.executable, str(HOOK_GATE)], capture_output=True, text=True,
            env=env, input=_prompt_json(_DEFAULT_PROMPT),
        )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_when_stdin_is_unparseable() -> None:
    """AC-3: if the UserPromptSubmit stdin payload cannot be parsed at all,
    the gate fails open (exit 0) rather than still evaluating the
    pick_required check blind."""
    result = _run_gate(
        "T-GATE-017", phase="design:ack-needed", track="M",
        stdin="this is not json{{{",
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_still_blocks_ordinary_prompt_with_pending_choice() -> None:
    """AC-3: pin — none of the new escape hatches weaken the baseline: an
    ordinary prompt on a pick_required:ack-needed ticket still blocks."""
    result = _run_gate(
        "T-GATE-018", phase="design:ack-needed", track="M",
        stdin=_prompt_json("what should I do next?"),
    )
    assert result.returncode == 2, result
    assert result.stdout == "", result.stdout


def test_lifecycle_verbs_derived_from_command_files() -> None:
    """AC-3: the gate's lifecycle-verb allowlist is derived from
    klc-plugin/commands/*.md, not typed by hand, so it cannot silently drift
    from the plugin's real slash commands."""
    gate = _load_hook_module("gate")
    expected = {p.stem for p in (PLUGIN_DIR / "commands").glob("*.md")}
    assert expected, "klc-plugin/commands/*.md is empty — fixture is broken"
    assert gate._lifecycle_verbs() == expected


# --- step-4: error paths that used to escape as an uncaught exception (AC-3) -


def test_gate_allows_when_status_json_is_not_an_object(tmp_path) -> None:
    """AC-3: `klc status --json` returning valid JSON that is not an object
    (e.g. a bare list) must still fail open with exit 0, not crash to 1 on
    the subsequent `.get()` call."""
    result = _run_gate(
        "T-GATE-019", phase="design:ack-needed", track="M",
        klc_bin=_write_stub_klc(tmp_path, "[1, 2]"),
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_when_phase_id_is_unhashable(tmp_path) -> None:
    """AC-3: a non-hashable `phase_id` (e.g. a list) in the status JSON must
    still fail open with exit 0, not crash to 1 on the `in <set>` check."""
    payload = json.dumps({"phase_id": [1, 2], "state": "ack-needed"})
    result = _run_gate(
        "T-GATE-020", phase="design:ack-needed", track="M",
        klc_bin=_write_stub_klc(tmp_path, payload),
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_when_klc_bin_has_unbalanced_quotes() -> None:
    """AC-3: a malformed KLC_BIN (unbalanced quotes, so shlex.split raises
    ValueError) must still fail open with exit 0, not crash to 1."""
    result = _run_gate(
        "T-GATE-021", phase="design:ack-needed", track="M",
        klc_bin="python3 'unbalanced",
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


# --- step-4: remind's real plain-text output is actually exercised (AC-6) --


def test_remind_hook_emits_plain_text_reminder_and_passes_contract_check(tmp_path) -> None:
    """AC-6: pin — when `klc remind` actually has something to say (a
    completable held ticket), the hook's real plain-text stdout is exercised
    and still passes the per-role contract check. Mirrors the identity +
    can_complete(`integrate`) fixture in tests/integration/test_remind.py."""
    identity = "gate-fixture@example.com"
    _git_init(tmp_path, identity)
    klc_dir = tmp_path / ".klc"
    klc_dir.mkdir()
    _bootstrap_ticket(klc_dir, "T-GATE-022", phase="integrate:work", track="M",
                      holder_id=identity)

    env = _make_env(tmp_path)
    env.pop("KLC_TICKET", None)
    env.pop("GIT_AUTHOR_EMAIL", None)
    env.pop("GIT_COMMITTER_EMAIL", None)

    result = subprocess.run(
        [sys.executable, str(HOOK_REMIND)], capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result
    assert result.stdout == "T-GATE-022 integrate is done — run klc ack\n", result.stdout
    _check_hook_result("remind.py", result.returncode, result.stdout)


# --- step-4: `klc status` must not drain the Jira queue (AC-8) -------------


def test_klc_status_does_not_drain_jira_queue(tmp_path) -> None:
    """AC-8: `klc status`, which the gate hook runs on every prompt, must not
    trigger the opportunistic Jira-queue drain. Draining is a network write
    with its own timeout, and status is meant to be a cheap read-only check
    (mirrors test_remind.py::test_remind_does_not_drain_jira_queue)."""
    klc_dir = tmp_path / ".klc"
    klc_dir.mkdir()
    _bootstrap_ticket(klc_dir, "T-GATE-023", phase="design:ack-needed", track="M")
    cfg_dir = klc_dir / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "jira.yml").write_text(
        "sync:\n  enabled: true\n  transport: rest\n", encoding="utf-8"
    )
    queue = klc_dir / "jira-queue.jsonl"
    # Non-canonical (no spaces): a drain-rewrite via json.dumps would reformat.
    payload = '{"ticket":"KLC-999","status":"In Progress","phase":"build:work"}\n'
    queue.write_text(payload, encoding="utf-8")

    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("JIRA_TOKEN", None)  # ensure push would fail (no drain expected anyway)
    result = subprocess.run(
        [sys.executable, str(KLC), "status", "T-GATE-023", "--json"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result
    assert queue.read_text(encoding="utf-8") == payload, (
        "klc status mutated the Jira queue (unexpected opportunistic-drain side effect)"
    )


# --- step-5: broader command forms + narrowed bypass scope (AC-3, AC-4) ----
#
# External review LOW findings on step-4 (ac=AC-3, ac=null, ac=AC-4):
#  1. the escape hatch only recognised "/klc:<verb>" and "klc <verb>", missing
#     the operator's everyday unprefixed project-skill form ("/ack ...") and
#     the shell-mode form ("!klc ack ...");
#  2. the bypass verb set was too broad (it exempted run/next/intake/publish/
#     ship too, and matched even when a second line of instructions followed
#     the command), weakening the goal that chatting can't slip past the gate
#     by accident;
#  3. the block message/docstring claimed KLC_GATE=off works "for the
#     session", but hooks only see the environment Claude Code started with.


def test_gate_allows_unprefixed_ack_slash_command_even_when_blocking() -> None:
    """AC-3: the operator's everyday unprefixed project-skill form (`/ack`,
    not only the plugin's namespaced `/klc:ack`) is recognised too."""
    result = _run_gate(
        "T-GATE-024", phase="design:ack-needed", track="M",
        stdin=_prompt_json("/ack T-GATE-024 --pick 1"),
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_unprefixed_status_slash_command_even_when_blocking() -> None:
    """AC-3: `/status` (unprefixed) is exempt too, not just `/klc:status`."""
    result = _run_gate(
        "T-GATE-025", phase="design:ack-needed", track="M",
        stdin=_prompt_json("/status T-GATE-025"),
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_allows_bang_klc_cli_form_even_when_blocking() -> None:
    """AC-3: the shell-mode form (`!klc ack ...`) is exempt too, not just the
    bare `klc ack ...` CLI form."""
    result = _run_gate(
        "T-GATE-026", phase="design:ack-needed", track="M",
        stdin=_prompt_json("!klc ack T-GATE-026 --pick 1"),
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_still_blocks_run_command_even_with_slash_klc_prefix() -> None:
    """AC-3: `run` mutates phase state (it's the orchestrator loop, not a
    pending-choice resolver or a read-only state report), so it is
    deliberately NOT in the narrowed bypass set — `/klc:run` must still be
    held while a pick is pending."""
    result = _run_gate(
        "T-GATE-027", phase="design:ack-needed", track="M",
        stdin=_prompt_json("/klc:run T-GATE-027"),
    )
    assert result.returncode == 2, result
    assert result.stdout == "", result.stdout


def test_gate_still_blocks_multiline_prompt_starting_with_exempt_command() -> None:
    """AC-3: a second line of instructions after an otherwise-exempt command
    means the operator is doing more than just unblocking the gate — the
    normal pick_required rule applies."""
    result = _run_gate(
        "T-GATE-028", phase="design:ack-needed", track="M",
        stdin=_prompt_json("/klc:ack T-GATE-028 --pick 1\nnow implement X"),
    )
    assert result.returncode == 2, result
    assert result.stdout == "", result.stdout


def test_gate_allows_single_line_exempt_command_even_when_blocking() -> None:
    """AC-3: pin — the single-line form of an exempt command (no trailing
    instructions) still passes, confirming the multiline restriction above
    doesn't over-tighten the common case."""
    result = _run_gate(
        "T-GATE-030", phase="design:ack-needed", track="M",
        stdin=_prompt_json("/ack T-GATE-030 --pick 1"),
    )
    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout


def test_gate_bypass_verbs_is_narrowed_curated_set() -> None:
    """AC-3: the gate's bypass-eligible verb set is narrowed to exactly the
    verbs that resolve a pending choice or purely report state — ack,
    status, abort, jump, step — excluding run, next, intake, publish and
    ship, which mutate phase state."""
    gate = _load_hook_module("gate")
    assert gate._gate_bypass_verbs() == {"ack", "status", "abort", "jump", "step"}
    for mutating_verb in ("run", "next", "intake", "publish", "ship"):
        assert mutating_verb not in gate._gate_bypass_verbs()


def test_gate_message_and_docstring_document_klc_gate_restart_requirement() -> None:
    """AC-4: the block message and the module docstring must not claim
    KLC_GATE=off works 'for the session' — hooks only see the environment
    Claude Code was started with, so it only takes effect if set before
    Claude Code starts, or via the settings `env`."""
    result = _run_gate("T-GATE-029", phase="design:ack-needed", track="M")
    assert result.returncode == 2, result
    assert "for the session" not in result.stderr, result.stderr
    assert "KLC_GATE=off" in result.stderr, result.stderr

    gate_doc = ast.get_docstring(ast.parse(HOOK_GATE.read_text(encoding="utf-8")))
    assert gate_doc is not None
    assert "for the session" not in gate_doc, gate_doc
    assert "KLC_GATE=off" in gate_doc, gate_doc
