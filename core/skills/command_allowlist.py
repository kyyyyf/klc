"""command_allowlist.py — KLC-174: the one gate a plan-step VERIFY command passes
before anything is executed.

Why it exists: a VERIFY line comes from impl-plan.md (or, tampered, from
steps.json) and is handed to a shell. Instead of trying to recognise every
dangerous construct, the gate is a short allowlist of test runners and it is
fail-closed: anything it cannot fully understand is refused, never run.

Grammar: segments separated by `&&`, `;` or `|`. EVERY segment must start with an
allowed program prefix. `$` (so `$(...)` and variables), backticks, newlines,
redirections (`<`, `>`, `2>&1`), process substitution, `||`, `&` and subshell
parentheses are all refused. The list is extensible only through the
`verify.allowed_programs` key of settings.yml (the caller passes it in).

NOT a sandbox: the gate decides which PROGRAM runs, not what the test code does.
A committed `conftest.py` or test file still runs arbitrary code. Only a few flags
that make a test runner import a module or write outside the repo are refused
(`_DENIED_FLAGS`).

Unusual on purpose: a raw `#` anywhere is refused (`shlex` would drop `a#b; cmd`
as a comment while the shell runs `cmd`), and the `$` and newline checks look at the RAW text, even inside
quotes. A quoted `$` is harmless in single quotes but the gate does not try to
tell the difference — a plan that needs it can use a script wrapper added to
`verify.allowed_programs`.

The segmentation idea (split on && ; | outside quotes, never trust a bare
substring match) follows `_segments` in klc-plugin/hooks/git_guard.py (KLC-172).
core must not import from klc-plugin, so the logic is re-done here with `shlex`
punctuation handling instead of a hand-written scanner.
"""
from __future__ import annotations

import shlex

DEFAULT_PROGRAMS = (("python3", "-m", "pytest"), ("pytest",), ("npm", "test"),
                    ("cargo", "test"), ("go", "test"), ("dotnet", "test"))
_SEPARATORS = {"&&", ";", "|"}
# Flags that make a runner load arbitrary code or write outside the repo, per
# program prefix. A long flag also matches `--flag=value`; a short one `-pVALUE`.
_PYTEST_DENIED = (("-p", "short"), ("-c", "short"), ("--basetemp", "long"),
                  ("--rootdir", "long"), ("--junitxml", "long"),
                  ("--junit-xml", "long"), ("-o", "short"), ("--override-ini", "long"))
_DENIED_FLAGS = {
    ("python3", "-m", "pytest"): _PYTEST_DENIED,
    ("pytest",): _PYTEST_DENIED,
    ("go", "test"): (("-exec", "long"),),
    ("cargo", "test"): (("--config", "long"),),
    ("npm", "test"): (("--eval", "long"),),
}
_OPERATOR_CHARS = set("&;|<>()")


def _fail(why: str) -> tuple[bool, str]:
    return False, f"command-not-allowed: {why}"


def check(command, extra_programs=()) -> tuple[bool, str]:
    """`(True, "")` when every segment is an allowed program, else
    `(False, "command-not-allowed: <program or construct>")`. Never raises."""
    if not isinstance(command, str) or not command.strip():
        return _fail("empty")
    for ch, name in (("$", "$"), ("`", "backtick"), ("\n", "newline"), ("\r", "newline")):
        if ch in command:
            return _fail(f"{name} (expansion or newline)" if ch != "\n" else name)
    if "#" in command:
        return _fail("comment")
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.commenters = ""
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError as exc:
        return _fail(f"unparsable ({exc})")
    try:
        extra = [tuple(shlex.split(p)) for p in (extra_programs or ()) if isinstance(p, str)]
    except ValueError:
        extra = []
    allowed = [tuple(p) for p in DEFAULT_PROGRAMS] + [p for p in extra if p]
    segment: list[str] = []
    for tok in tokens + [";"]:
        if set(tok) <= _OPERATOR_CHARS and tok not in _SEPARATORS:
            return _fail(f"operator {tok}")
        if tok in _SEPARATORS:
            if not segment:
                return _fail(f"empty segment before {tok}")
            prefix = next((p for p in allowed if tuple(segment[:len(p)]) == p), None)
            if prefix is None:
                return _fail(segment[0])
            for flag, kind in _DENIED_FLAGS.get(prefix, ()):
                for arg in segment[len(prefix):]:
                    if arg == flag or arg.startswith(flag + "=") or \
                            (kind == "short" and arg.startswith(flag)):
                        return _fail(f"flag {flag}")
            segment = []
        else:
            segment.append(tok)
    return True, ""
