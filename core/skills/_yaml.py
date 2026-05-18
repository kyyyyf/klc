"""Minimal YAML subset parser shared by klc config loaders.

Supported:
  - top-level mapping or list;
  - lists of mappings, inline key on list entry (`- key: value`);
  - string scalars (quoted or bare), bool, null, integer;
  - flow lists in values (`key: [a, b, c]`);
  - comments (`#` and trailing ` #`).

Not supported: anchors, tags, multi-line scalars, block literal blocks,
nested flow mappings. Adequate for `config/phases.yml`,
`config/models.yml`, and the seed files shipped under `config/`.

PyYAML is avoided on purpose — klc has no runtime deps besides stdlib,
and a permissive 100-line parser is sufficient for our flat files.
"""
from __future__ import annotations

from typing import Any


def parse(text: str) -> Any:
    """Parse a YAML document. Returns a nested structure of
    dict/list/str/bool/int/None. Raises ValueError on malformed input."""
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        stripped = raw.rstrip()
        content = stripped.lstrip()
        if not content or content.startswith("#"):
            continue
        indent = len(stripped) - len(content)
        # strip trailing inline comment (only when # is preceded by whitespace)
        if " #" in content:
            content = content.split(" #", 1)[0].rstrip()
        lines.append((indent, content))

    pos = [0]

    def parse_block(indent: int) -> Any:
        if pos[0] >= len(lines):
            return None
        cur_indent, cur = lines[pos[0]]
        if cur_indent < indent:
            return None
        if cur.startswith("- "):
            return parse_list(cur_indent)
        return parse_map(cur_indent)

    def parse_list(indent: int) -> list:
        out: list = []
        while pos[0] < len(lines):
            cur_indent, cur = lines[pos[0]]
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise ValueError(f"unexpected indent at {cur!r}")
            if not cur.startswith("- "):
                break
            rest = cur[2:].strip()
            pos[0] += 1
            if ":" in rest and not rest.startswith("["):
                # Inline key: synthesize a map starting here.
                k, _, v = rest.partition(":")
                k, v = k.strip(), v.strip()
                entry: dict = {}
                if v:
                    entry[k] = _scalar(v)
                else:
                    entry[k] = parse_block(indent + 2)
                # Consume more keys at indent + 2 belonging to this list item.
                while pos[0] < len(lines):
                    ni, nc = lines[pos[0]]
                    if ni <= indent:
                        break
                    if ni != indent + 2:
                        break
                    if nc.startswith("- "):
                        break
                    kk, _, vv = nc.partition(":")
                    kk, vv = kk.strip(), vv.strip()
                    pos[0] += 1
                    if vv:
                        entry[kk] = _scalar(vv)
                    else:
                        entry[kk] = parse_block(indent + 4)
                out.append(entry)
            else:
                out.append(_scalar(rest))
        return out

    def parse_map(indent: int) -> dict:
        out: dict = {}
        while pos[0] < len(lines):
            cur_indent, cur = lines[pos[0]]
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise ValueError(f"unexpected indent at {cur!r}")
            if cur.startswith("- "):
                break
            if ":" not in cur:
                raise ValueError(f"expected key:value, got {cur!r}")
            k, _, v = cur.partition(":")
            k, v = k.strip(), v.strip()
            pos[0] += 1
            if v:
                out[k] = _scalar(v)
            else:
                out[k] = parse_block(indent + 2)
        return out

    def _scalar(s: str) -> Any:
        s = s.strip()
        if s == "":
            return None
        # inline flow list / flow mapping.
        if s.startswith("[") and s.endswith("]"):
            body = s[1:-1].strip()
            if not body:
                return []
            return [_scalar(x.strip()) for x in body.split(",")]
        if s.startswith("{") and s.endswith("}"):
            body = s[1:-1].strip()
            if not body:
                return {}
            out: dict = {}
            for pair in _split_flow(body):
                if ":" not in pair:
                    raise ValueError(f"flow mapping entry missing ':' in {pair!r}")
                k, _, v = pair.partition(":")
                out[k.strip()] = _scalar(v.strip())
            return out
        if s.startswith('"') and s.endswith('"'):
            return bytes(s[1:-1], "utf-8").decode("unicode_escape")
        if s.startswith("'") and s.endswith("'"):
            return s[1:-1]
        lower = s.lower()
        if lower in ("null", "~"):
            return None
        if lower == "true":
            return True
        if lower == "false":
            return False
        if s.lstrip("-").isdigit():
            return int(s)
        return s

    result = parse_block(0)
    if pos[0] != len(lines):
        raise ValueError(f"unparsed input at line {pos[0]}: {lines[pos[0]]}")
    return result


def _split_flow(body: str) -> list[str]:
    """Split a flow-mapping body on commas at depth 0, so that
    `a: 1, b: [2, 3]` parses into `["a: 1", "b: [2, 3]"]`."""
    out: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in body:
        if ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf.clear()
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return out
