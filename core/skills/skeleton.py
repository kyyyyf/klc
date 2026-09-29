#!/usr/bin/env python3
"""skeleton.py — `klc skeleton <file>`: an on-demand, never-stored outline of
ONE file, with inclusive 1-based `[start-end]` line ranges (KLC-139).

Computed at call time (C-002): no cache, no index entry, so it cannot go
stale, unlike the stored `inventory.json` (KLC-136/KLC-137). Python goes
through the standard-library `ast` and lists everything — imports, module
variables, classes with members, functions, private names included. Every
other language is rule-scoped: it lists only what the active profile's
ast-grep rules match (C-001), grouped by rule id and message — no per-language
branch, no extension table (AC-6, AC-9).

Limits (`config/settings.yml`, `core/skills/settings.py`): `skeleton.max_fields`
(data members per class before `[N more truncated]`, Q-001),
`skeleton.max_line` (characters per rendered line, header included, D-208),
`skeleton.max_bytes` (files above this size are refused).
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_file_dir) not in sys.path:
    sys.path.insert(0, str(_file_dir))
import settings  # noqa: E402
import deterministic_inventory as _di  # noqa: E402
import tools as _tools  # noqa: E402

_PY_SUFFIXES = (".py", ".pyi")          # the one allowed dispatch (C-001, Q-007)


@dataclass(frozen=True)
class SkeletonResult:
    text: str
    refused: bool

    @property
    def exit_code(self) -> int:
        return 1 if self.refused else 0


@dataclass(frozen=True)
class _Limits:
    max_fields: int
    max_line: int
    max_bytes: int


class _Refusal(Exception):
    """Internal: carries one AC-7 reason up to skeleton(); never escapes it."""


# --- rendering ----------------------------------------------------------------

def _fit_header(shown: str, suffix: str, max_line: int) -> str:
    """The header keeps its `(language, ...)` suffix the way an entry keeps its
    range (D-208, impl-plan review F-4): only the path part is cut."""
    line = f"{shown} {suffix}" if suffix else shown
    if len(line) <= max_line:
        return line
    room = max(max_line - len(" [truncated] ") - len(suffix), 0)
    return f"{shown[:room]} [truncated] {suffix}"


def _fit(indent: str, text: str, rng: str, max_line: int) -> str:
    """D-208: cut *text* only, keep *indent* and *rng* (the range) intact."""
    tail = f" {rng}" if rng else ""
    line = f"{indent}{text}{tail}"
    if len(line) <= max_line:
        return line
    room = max(max_line - len(indent) - len(" [truncated]") - len(tail), 0)
    return f"{indent}{text[:room]} [truncated]{tail}"


def _render(header_line: str, entries: list, max_line: int) -> str:
    lines = [header_line]
    if not entries:
        lines.append("(no symbols)")
    else:
        for indent, text, rng in entries:
            lines.append(_fit(" " * (indent * 2), text, rng or "", max_line))
    return "\n".join(lines) + "\n"


def _range_str(lineno: int, end_lineno: int) -> str:
    if lineno == end_lineno:
        return f"[{lineno}]"
    return f"[{lineno}-{end_lineno}]"


def _line_count(text: str) -> int:
    """The header's line count, counted the way `ast`'s line numbers are —
    `\\r\\n`, `\\r` or `\\n` as a break — not `str.splitlines()`'s broader
    break set (`\\x0c`, U+2028, ...), which can claim more lines than any
    entry's range, or the file's real line count, ever shows (review LOW,
    code-review/external-review)."""
    if not text:
        return 0
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalised.count("\n") + (0 if normalised.endswith("\n") else 1)


# --- Python engine (AC-3, AC-4, AC-5) ------------------------------------------

def _module_level(stmts):
    """D-206: descend into module-level `if` (body, orelse) and `try` (body,
    handlers, orelse, finalbody) only — never `with`, `for` or `match`."""
    for node in stmts:
        if isinstance(node, ast.If):
            yield from _module_level(node.body)
            yield from _module_level(node.orelse)
        elif isinstance(node, ast.Try):
            yield from _module_level(node.body)
            for handler in node.handlers:
                yield from _module_level(handler.body)
            yield from _module_level(node.orelse)
            yield from _module_level(node.finalbody)
        else:
            yield node


def _def_start(node) -> int:
    """AC-3: a range runs from the first decorator line (or the definition
    line) to `end_lineno`."""
    decorators = getattr(node, "decorator_list", None) or []
    if decorators:
        return min(d.lineno for d in decorators)
    return node.lineno


def _func_text(node) -> str:
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    args_text = ast.unparse(node.args)
    text = f"{prefix}{node.name}({args_text})"
    if node.returns is not None:
        text += f" -> {ast.unparse(node.returns)}"
    return text


def _module_variable(node):
    """D-206/Q-002: a plain-name module assignment or annotated field, or
    None when the target is not a plain name (a tuple target is skipped)."""
    if isinstance(node, ast.AnnAssign):
        if not isinstance(node.target, ast.Name):
            return None
        ann = ast.unparse(node.annotation)
        return f"{node.target.id}: {ann}", node.lineno, node.end_lineno
    if isinstance(node, ast.Assign):
        if not node.targets or not all(isinstance(t, ast.Name) for t in node.targets):
            return None
        names = ", ".join(t.id for t in node.targets)
        return names, node.lineno, node.end_lineno
    return None


def _import_groups(import_nodes) -> list:
    """D-207: absolute imports grouped by top-level package (`self` first,
    then sorted items); relative imports printed one per line, as written,
    after all absolute lines, sorted. Items are deduplicated."""
    absolute: dict = {}
    relative: list = []

    def _add(pkg, item):
        items = absolute.setdefault(pkg, [])
        if item not in items:
            items.append(item)

    for node in import_nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                pkg, _, rest = alias.name.partition(".")
                item = rest if rest else "self"
                if alias.asname:
                    item = f"self as {alias.asname}" if item == "self" else f"{item} as {alias.asname}"
                _add(pkg, item)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                mod = node.module or ""
                dots = "." * node.level
                for alias in node.names:
                    name = alias.name if not alias.asname else f"{alias.name} as {alias.asname}"
                    line = f"{dots}{mod}.{name}" if mod else f"{dots}{name}"
                    if line not in relative:
                        relative.append(line)
            else:
                mod = node.module or ""
                pkg, _, rest = mod.partition(".")
                for alias in node.names:
                    name = alias.name if not alias.asname else f"{alias.name} as {alias.asname}"
                    item = f"{rest}.{name}" if rest else name
                    _add(pkg, item)

    lines: list = []
    for pkg in sorted(absolute):
        items = absolute[pkg]
        self_items = [it for it in items if it == "self" or it.startswith("self as ")]
        rest_items = sorted(it for it in items if it not in self_items)
        ordered = self_items + rest_items
        if len(ordered) == 1:
            only = ordered[0]
            if only == "self":
                lines.append(pkg)
            elif only.startswith("self as "):
                lines.append(f"{pkg} as {only[len('self as '):]}")
            else:
                lines.append(f"{pkg}.{only}")
        else:
            lines.append(f"{pkg}.{{{', '.join(ordered)}}}")
    for rel in sorted(relative):
        lines.append(rel)
    return lines


def _class_entries(node: ast.ClassDef, limits: _Limits, depth: int) -> list:
    """D-206: class members are the class body's DIRECT statements only (no
    descent into nested if/try). Methods and nested classes are always
    listed; data members (assignments/annotations) are capped at
    `limits.max_fields` (Q-001), with one `[N more truncated]` line."""
    start = _def_start(node)
    entries = [(depth, node.name, _range_str(start, node.end_lineno))]
    child_indent = depth + 1

    data_positions = [i for i, child in enumerate(node.body)
                       if _module_variable(child) is not None]
    keep = set(data_positions[:limits.max_fields])

    for i, child in enumerate(node.body):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cstart = _def_start(child)
            entries.append((child_indent, _func_text(child),
                             _range_str(cstart, child.end_lineno)))
        elif isinstance(child, ast.ClassDef):
            entries.extend(_class_entries(child, limits, child_indent))
        elif i in keep:
            text, lineno, end_lineno = _module_variable(child)
            entries.append((child_indent, text, _range_str(lineno, end_lineno)))

    if len(data_positions) > limits.max_fields:
        truncated = len(data_positions) - limits.max_fields
        entries.append((child_indent, f"[{truncated} more truncated]", None))
    return entries


_TOO_DEEP = "too deeply nested to parse — read the file instead"


def _python_entries(text: str, limits: _Limits) -> list:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # SyntaxWarning on odd escapes is not a refusal
            tree = ast.parse(text)
    except (SyntaxError, ValueError):        # ValueError: NUL bytes on older Pythons
        raise _Refusal("syntax errors — read the file instead")
    except (RecursionError, MemoryError):
        # A syntactically VALID but deeply nested file (e.g. a long chained
        # expression) can blow CPython's own parser stack (review HIGH #2).
        # This is honestly a different reason than "syntax errors" — the
        # file is not broken — so it gets its own wording (impl-plan D-8-1).
        raise _Refusal(_TOO_DEEP)

    try:
        stmts = list(_module_level(tree.body))   # descends module-level if/try only (D-206)

        import_nodes = [n for n in stmts if isinstance(n, (ast.Import, ast.ImportFrom))]
        class_nodes = [n for n in stmts if isinstance(n, ast.ClassDef)]
        func_nodes = [n for n in stmts if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        var_nodes = [n for n in stmts if _module_variable(n) is not None]

        entries: list = []
        if import_nodes:
            start = min(n.lineno for n in import_nodes)
            end = max(n.end_lineno for n in import_nodes)
            entries.append((0, "imports", _range_str(start, end)))
            for line in _import_groups(import_nodes):
                entries.append((1, line, None))
        if var_nodes:
            entries.append((0, "variables", None))
            for n in var_nodes:
                vtext, lineno, end_lineno = _module_variable(n)
                entries.append((1, vtext, _range_str(lineno, end_lineno)))
        if class_nodes:
            entries.append((0, "classes", None))
            for n in class_nodes:
                entries.extend(_class_entries(n, limits, 1))
        if func_nodes:
            entries.append((0, "functions", None))
            for n in func_nodes:
                start = _def_start(n)
                entries.append((1, _func_text(n), _range_str(start, n.end_lineno)))
    except (RecursionError, MemoryError):
        # Defensive: entry-building also walks the tree (ast.unparse on a
        # deeply nested annotation/default has the same exposure, review
        # HIGH #2's own note), even though the golden repro trips ast.parse
        # itself first.
        raise _Refusal(_TOO_DEEP)
    return entries


# --- ast-grep engine (AC-6, AC-7, AC-8, AC-9; D-201/D-202) ---------------------

#  DOTALL + finditer over the WHOLE stderr text, not per-line: this one
# diagnostic line embeds the raw file path, so a path containing a literal
# newline splits it into two physical lines (review MEDIUM #4b) — a
# per-line `^...$` match would silently miss it and fall back to a false
# "unsupported language".
_ENTITY_RE = re.compile(r"sg: entity\|file\|.*?: language=([^,]*),appliedRuleCount=(\d+)",
                        re.DOTALL)
_SENTINEL = "sg: summary|file:"


def _scan(exe, cwd, *args) -> tuple:
    """One ast-grep call -> (parsed JSON list, stderr). Every failure is a
    refusal (AC-7). `encoding=`/`errors=` are explicit (review LOW #6): the
    locale-dependent `text=True` mode can mojibake or crash on non-ASCII
    match text in a non-UTF-8 locale; ast-grep's own JSON/diagnostics are
    always UTF-8."""
    try:
        r = subprocess.run([str(exe), "scan", *args], capture_output=True,
                            encoding="utf-8", errors="replace",
                            cwd=cwd, timeout=60)
    except subprocess.TimeoutExpired:
        raise _Refusal("ast-grep failed (timeout) — read the file instead")
    except OSError as exc:
        raise _Refusal(f"ast-grep failed ({type(exc).__name__}) — read the file instead")
    if r.returncode != 0:
        raise _Refusal(f"ast-grep failed (exit {r.returncode}) — read the file instead")
    try:
        return json.loads(r.stdout or "[]"), r.stderr
    except json.JSONDecodeError:
        raise _Refusal("ast-grep failed (bad JSON) — read the file instead")


def _group_by_rule(raw_matches: list) -> list:
    """D-209: one header per rule (`<rule id>: <message>`), groups sorted by
    rule id, entries by `(start, end)`; identical `(rule, start, end)`
    matches collapse into one entry (AC-6)."""
    groups: dict = {}
    for m in raw_matches:
        if not isinstance(m, dict):
            continue
        rng = _di.match_line_range(m)
        if rng is None:
            continue
        rule_id = m.get("ruleId") or ""
        message = m.get("message") or ""
        first_line = (m.get("text") or "").splitlines()[0].strip() if m.get("text") else ""
        if first_line.endswith("{"):
            first_line = first_line[:-1].rstrip()
        bucket = groups.setdefault(rule_id, {"message": message, "entries": {}})
        bucket["entries"].setdefault(rng, first_line)   # keep the FIRST match's text (F-207 dedup)

    entries: list = []
    for rule_id in sorted(groups):
        bucket = groups[rule_id]
        entries.append((0, f"{rule_id}: {bucket['message']}", None))
        for start, end in sorted(bucket["entries"]):
            entries.append((1, bucket["entries"][(start, end)], _range_str(start, end)))
    return entries


def _astgrep_entries(real: Path, raw: bytes) -> tuple:
    """D-201/D-202: two ast-grep calls with one temp config. Call 1
    (`--inspect entity`) decides coverage and yields the matches; call 2 (one
    `--inline-rules {kind: ERROR}` probe in the language call 1 reported)
    decides syntax errors.

    *raw* is checked as strict UTF-8 BEFORE either call (impl-plan D-8-2):
    ast-grep 0.42.1 silently SKIPS a file it cannot decode as UTF-8 — its
    `--inspect` stderr then has the `summary|file:` sentinel but no
    `entity|file` line, indistinguishable from genuine zero rule coverage,
    so the old code reported the dishonest 'unsupported language' (review
    MEDIUM #4). Deciding it ourselves, first, is cheaper than parsing
    `skippedFileCount` out of ast-grep's stderr and gives an honest reason
    either way."""
    exe = _tools.resolve_tool("ast-grep")
    if not exe:
        raise _Refusal("ast-grep unavailable — read the file instead")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _Refusal("not valid UTF-8 — read the file instead")
    ruleset = _di.resolve_ruleset()
    cfg = {"ruleDirs": ruleset["rule_dirs"]}
    if ruleset["language_globs"]:
        cfg["languageGlobs"] = ruleset["language_globs"]
    with tempfile.TemporaryDirectory(prefix="klc-skeleton-") as td:
        cfg_path = Path(td) / "sgconfig.yml"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")        # JSON is YAML (F-205)
        out, err = _scan(exe, td, "--config", str(cfg_path), "--inspect", "entity",
                          "--json=compact", str(real))
        if _SENTINEL not in err:
            raise _Refusal("ast-grep failed (no inspect output) — read the file instead")
        hits = list(_ENTITY_RE.finditer(err))
        if not hits or int(hits[-1].group(2)) == 0:
            raise _Refusal(f"unsupported language: {real.suffix or '(no extension)'}")
        lang = hits[-1].group(1)
        probe = f"id: klc-skeleton-syntax\nlanguage: {lang}\nrule: {{kind: ERROR}}\n"
        probe_out, _ = _scan(exe, td, "--config", str(cfg_path), "--inline-rules", probe,
                              "--json=compact", str(real))
        if probe_out:
            raise _Refusal("syntax errors — read the file instead")
    return lang.lower(), _group_by_rule(out)


# --- entry point ----------------------------------------------------------------

def skeleton(path) -> SkeletonResult:
    shown = str(path)
    limits = _Limits(settings.skeleton_max_fields(), settings.skeleton_max_line(),
                      settings.skeleton_max_bytes())
    try:
        real = Path(path).resolve()           # symlink resolved before the size check
        if not real.is_file():
            raise _Refusal(f"not a file: {shown}")
        try:
            size = real.stat().st_size
        except OSError as exc:
            # review MEDIUM #3: is_file() succeeding does not mean stat/read
            # will — a chmod-000 file stats fine but fails to open.
            raise _Refusal(f"cannot read file: {exc.strerror or exc}")
        if size > limits.max_bytes:
            raise _Refusal(f"file too large ({size} bytes > {limits.max_bytes})"
                            " — read with offset/limit")
        is_python = real.suffix in _PY_SUFFIXES
        if size == 0:                          # decided before ast-grep (AC-8)
            header = _fit_header(shown, "(python, 0 lines)" if is_python else "(0 lines)",
                                  limits.max_line)
            return SkeletonResult(_render(header, [], limits.max_line), False)
        try:
            raw = real.read_bytes()
        except OSError as exc:
            raise _Refusal(f"cannot read file: {exc.strerror or exc}")
        if is_python:
            # utf-8-sig: a leading BOM (U+FEFF) is otherwise an invalid
            # non-printable character to ast.parse, so a BOM-prefixed file
            # that `python3` itself runs fine was falsely refused as a
            # syntax error (review HIGH #1).
            text = raw.decode("utf-8-sig", errors="replace")
            header = _fit_header(shown, f"(python, {_line_count(text)} lines)",
                                  limits.max_line)
            entries = _python_entries(text, limits)
        else:
            lang, entries = _astgrep_entries(real, raw)
            header = _fit_header(
                shown, f"({lang}, rule-scoped: only what the profile's rules match)",
                limits.max_line)
    except _Refusal as r:
        return SkeletonResult(f"{shown}: {r}\n", True)   # refusal lines are never cut (D-208)
    return SkeletonResult(_render(header, entries, limits.max_line), False)


_USAGE = "usage: klc skeleton <file>"


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--":      # the standard separator (review LOW #7):
        args = args[1:]               # `klc skeleton -- -x.ts` accepts a
                                       # path that itself begins with '-'.
    if len(args) != 1:
        sys.stderr.write(_USAGE + "\n")
        return 2
    result = skeleton(args[0])
    sys.stdout.write(result.text)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
