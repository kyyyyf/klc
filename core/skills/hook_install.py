#!/usr/bin/env python3
"""hook_install.py — KLC-107: git-resolved hooks directory and a
deterministic hook-manager detector table (C-001, AC-14, AC-19).

`klc install` never writes into a directory another manager owns (C-001);
it wires the plain-git hook only when `detect()` says nothing else is
watching the slot, and prints a copy-ready snippet otherwise.
"""
from __future__ import annotations

import stat
import subprocess
from pathlib import Path

# The tuple ORDER is the specificity ranking, and it is a data structure
# precisely so a test can assert it. A named manager's own config file is
# stronger evidence than a bare core.hooksPath override: the override says
# the slot moved, not who moved it. Among named managers no one is
# intrinsically more specific, so the order is fixed by declaration and
# every other hit lands in `also_detected`.
DETECTORS = (
    ("pre-commit", (".pre-commit-config.yaml", ".pre-commit-config.yml")),
    ("lefthook",   ("lefthook.yml", "lefthook.yaml", ".lefthook.yml",
                    "lefthook.toml", "lefthook.json")),
    ("husky",      (".husky",)),
)
MODES = ("direct", "snippet", "disabled")

_SNIPPETS = {
    "pre-commit": (
        "# .pre-commit-config.yaml — add klc as a local hook:\n"
        "#   - repo: local\n"
        "#     hooks:\n"
        "#       - id: klc-{cmd_id}\n"
        "#         name: klc {cmd}\n"
        "#         entry: {klc_cmd}\n"
        "#         language: system\n"
        "#         pass_filenames: false\n"
    ),
    "lefthook": (
        "# lefthook.yml — add under pre-commit.commands:\n"
        "# pre-commit:\n"
        "#   commands:\n"
        "#     klc-{cmd_id}:\n"
        "#       run: {klc_cmd}\n"
    ),
    "husky": (
        "# .husky/pre-commit — append:\n"
        "{klc_cmd}\n"
    ),
    "hooksPath": (
        "# core.hooksPath is set to a directory another tool manages — add a\n"
        "# line invoking klc to whatever hook script lives there:\n"
        "{klc_cmd}\n"
    ),
}


def resolve_hooks_dir(repo) -> Path | None:
    """Ask git, never assume `.git/hooks` — worktrees and submodules differ."""
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
                       capture_output=True, text=True, timeout=5)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return (Path(repo) / r.stdout.strip()).resolve()


def _hooks_path_config(repo) -> str:
    r = subprocess.run(["git", "-C", str(repo), "config", "--get", "core.hooksPath"],
                       capture_output=True, text=True, timeout=5)
    return r.stdout.strip() if r.returncode == 0 else ""


def detect(repo) -> dict:
    """Return `{mode, manager, evidence, also_detected, hooks_dir}`.

    Deterministic: the winner is the FIRST hit in `DETECTORS` declaration
    order (never filesystem/dict iteration order), with a non-default
    `core.hooksPath` appended last as the weakest-specificity signal
    (Q-005 / AC-19b: a managed hooksPath with no named manager still
    yields the snippet mode)."""
    repo = Path(repo)
    hits = [(name, marker) for name, markers in DETECTORS
            for marker in markers if (repo / marker).exists()]
    hooks_path_cfg = _hooks_path_config(repo)
    if hooks_path_cfg:
        hits.append(("hooksPath", f"core.hooksPath={hooks_path_cfg}"))
    hooks_dir = resolve_hooks_dir(repo)
    if hits:
        manager, evidence = hits[0]
        return {"mode": "snippet", "manager": manager, "evidence": evidence,
                "also_detected": [n for n, _ in hits[1:]], "hooks_dir": hooks_dir}
    if hooks_dir is None:
        return {"mode": "disabled", "manager": "none",
                "evidence": "git reported no hooks directory",
                "also_detected": [], "hooks_dir": None}
    return {"mode": "direct", "manager": "none",
            "evidence": f"no hook manager detected; git hooks dir {hooks_dir}",
            "also_detected": [], "hooks_dir": hooks_dir}


def render_snippet(manager: str, klc_cmd: str) -> str:
    tmpl = _SNIPPETS.get(manager, "{klc_cmd}\n")
    cmd_id = klc_cmd.replace(" ", "-").replace("/", "-")
    return tmpl.format(klc_cmd=klc_cmd, cmd=klc_cmd, cmd_id=cmd_id)


# The config file(s) each named manager's detector markers live in — the
# same files `DETECTORS` matches on, read back to check whether an operator
# pasted the klc invocation into them (used by index_health.hook, step-9).
_MANAGER_CONFIG_FILES = {
    "pre-commit": (".pre-commit-config.yaml", ".pre-commit-config.yml"),
    "lefthook": ("lefthook.yml", "lefthook.yaml", ".lefthook.yml",
                "lefthook.toml", "lefthook.json"),
    "husky": (".husky/pre-commit",),
}


def manager_config_mentions_klc(repo, manager: str) -> bool:
    """True if the detected manager's own configuration already invokes
    klc (`klc update` / `klc.py update` / a klc shim path)."""
    repo = Path(repo)
    for rel in _MANAGER_CONFIG_FILES.get(manager, ()):
        p = repo / rel
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "klc" in text:
            return True
    return False


# --------------------------------------------------------------------------- #
# step-8 — writing the hook, and recording the decision
# --------------------------------------------------------------------------- #

MARKER = "# klc-hook v1 — generated by `klc install`; edit klc's hooks/pre-commit instead"
_CHAINED_NAME = "pre-commit.pre-klc"


class HookChainCollision(RuntimeError):
    """Raised when `pre-commit.pre-klc` already holds a DIFFERENT non-klc
    hook than the one about to be chained. `Path.rename` silently replaces
    an existing destination on POSIX, so writing through it would otherwise
    permanently and silently lose whatever was chained there before
    (review MEDIUM finding) — fail closed instead (C-006: never silently
    destroy)."""


def _existing_chain(current_text: str) -> str | None:
    for line in current_text.splitlines():
        line = line.strip()
        if line.startswith('PRIOR="$(dirname "$0")/') and line.endswith('"'):
            return line.split("/", 1)[1].rstrip('"')
    return None


def _shim(framework_root, chained_to: str | None = None) -> str:
    # KLC-107 [!DECISION D-203] (finding F-3): deliberately NO `set -e`. With
    # it, the chained-hook executability test below would abort the WHOLE
    # script whenever the test is false, and any exec failure would exit
    # non-zero and BLOCK THE COMMIT. Constraint C-006 says a misconfigured
    # hook must never block a commit, so every failure path here is explicit
    # instead of relying on shell strictness.
    lines = [
        "#!/usr/bin/env sh",
        MARKER,
        "set -u",
        f'KLC_FRAMEWORK_ROOT="{framework_root}"',
        "export KLC_FRAMEWORK_ROOT",
    ]
    if chained_to:
        # Preserve, never clobber: the previous hook runs first and ITS exit
        # status still decides the commit — the fail-open guard below must
        # not swallow it.
        lines += [
            f'PRIOR="$(dirname "$0")/{chained_to}"',
            'if [ -x "$PRIOR" ]; then',
            '  "$PRIOR" "$@" || exit $?',
            "fi",
        ]
    lines += [
        # C-006 fail-open guard: a framework root that was moved, deleted or
        # lives on an unmounted path degrades to a warning, not a blocked
        # commit.
        'if [ ! -x "$KLC_FRAMEWORK_ROOT/hooks/pre-commit" ]; then',
        '  echo "klc pre-commit: framework not found at $KLC_FRAMEWORK_ROOT'
        ' — skipping klc checks (re-run \\`klc install\\` to re-wire)" >&2',
        "  exit 0",
        "fi",
        'exec "$KLC_FRAMEWORK_ROOT/hooks/pre-commit" "$@"',
    ]
    return "\n".join(lines) + "\n"


def write_hook(hooks_dir, framework_root) -> str:
    """Write the klc shim into `hooks_dir/pre-commit`. Returns one of
    `written`, `chained`, `unchanged` (AC-15)."""
    hooks_dir = Path(hooks_dir)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    target = hooks_dir / "pre-commit"
    chained_to = None
    if target.exists():
        current = target.read_text(encoding="utf-8", errors="ignore")
        if MARKER in current:
            wanted = _shim(framework_root, _existing_chain(current))
            if current == wanted:
                return "unchanged"          # AC-15: byte-identical on re-run
            target.write_text(wanted, encoding="utf-8")
            _make_executable(target)
            return "written"
        # A pre-existing non-klc hook — preserve it by chaining, never
        # overwrite (AC-15).
        chained_to = _CHAINED_NAME
        chain_path = hooks_dir / chained_to
        if chain_path.exists():
            existing_chained = chain_path.read_text(encoding="utf-8", errors="ignore")
            if existing_chained != current:
                raise HookChainCollision(
                    f"{chain_path} already holds a DIFFERENT chained hook; "
                    f"refusing to overwrite it by chaining the current "
                    f"{target} — move or rename the existing file, then "
                    "re-run `klc install`."
                )
            # identical content already chained — safe to replace in place,
            # no data would be lost.
        target.rename(chain_path)
    target.write_text(_shim(framework_root, chained_to), encoding="utf-8")
    _make_executable(target)
    return "chained" if chained_to else "written"


def _make_executable(p: Path) -> None:
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


_BLOCK_BEGIN = "# BEGIN klc install (managed — rewritten by `klc install`)"
_BLOCK_END = "# END klc install (managed)"


def record_mode(project, mode: str, location: str) -> None:
    """AC-17: the single source of truth `klc doctor`'s index-hook check
    reads. Rewrites a marker-delimited managed block so a second install
    replaces it instead of appending a duplicate.

    review-fix (MEDIUM): record_mode ONLY owns `hook_mode`/`hook_location`
    within the managed `index:` block — a sibling key already present there
    (e.g. a hand-set `refresh_budget_seconds`, which config/settings.yml's own
    seed comment explicitly documents as NOT install-managed) must survive a
    second `klc install`. Merges into the existing block instead of
    regenerating it from a fixed template."""
    path = Path(project) / ".klc" / "config" / "settings.yml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    sibling_lines: list[str] = []
    if _BLOCK_BEGIN in text and _BLOCK_END in text:
        head, _, rest = text.partition(_BLOCK_BEGIN)
        body, _, tail = rest.partition(_BLOCK_END + "\n")
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "index:":
                continue
            key = stripped.split(":", 1)[0].strip()
            if key in ("hook_mode", "hook_location"):
                continue
            sibling_lines.append(line)
    else:
        head = text.rstrip("\n") + "\n\n" if text.strip() else ""
        tail = ""
    block = (f"{_BLOCK_BEGIN}\nindex:\n  hook_mode: {mode}\n"
             f"  hook_location: {location}\n")
    for line in sibling_lines:
        block += line + "\n"
    block += f"{_BLOCK_END}\n"
    text = head + block + tail
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
