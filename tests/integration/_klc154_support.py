"""Shared test support for the KLC-154 (migrate stored findings to the one
shape) test suite.

Not collected by pytest itself — helpers only. Every ``test_klc154_*`` module
builds its own scratch project through :func:`make_project`, which points
``PROJECT_ROOT`` at a throwaway ``tmp_path`` tree via ``monkeypatch`` — no
test in this ticket's suite reads or writes the live ``.klc/tickets`` tree
(KLC-136, impl-plan.md "Rules that hold across every step").

One test module belongs to one step; this module is the shared exception —
step-1 creates it and later steps only ADD helper functions here, never
change an existing one (mirrors `tests/integration/_klc133_support.py`'s own
rule). Step-7 (review-fix) adds `push_peer_update`.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


def make_project(tmp_path: Path, monkeypatch) -> Path:
    """A scratch project with an empty `.klc/tickets/` tree; `PROJECT_ROOT`
    is monkeypatched to point at it. Returns the tickets directory
    (`klc_tickets_dir()` of the scratch root)."""
    project = tmp_path / "project"
    tickets = project / ".klc" / "tickets"
    tickets.mkdir(parents=True)
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    return tickets


def add_ticket(tickets: Path, key: str, files: dict, phase: str = "archived") -> Path:
    """One ticket directory under *tickets*: a `meta.json` (phase *phase*)
    plus every `rel_path -> content` of *files* (`str` is written as UTF-8
    text, `bytes` written as-is — needed for the CRLF md-rewrite cases).
    Returns the ticket directory."""
    tdir = tickets / key
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": key, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    for rel, content in files.items():
        path = tdir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return tdir


def old_independent(n: int, **over) -> list[dict]:
    """*n* old-shape INDEPENDENT finding dicts (`id`, `category`, `severity`,
    `detail`, `ref`, `suggested_fix`) — the pre-KLC-127 shape a spec/
    test-plan/impl-plan/drift reviewer used to emit. *over* overrides the
    per-record defaults (applied to every record; callers wanting distinct
    per-record values build the list by hand instead)."""
    out = []
    for i in range(1, n + 1):
        rec = {
            "id": f"F-{i}",
            "category": "infidelity",
            "severity": "high",
            "detail": f"detail {i}",
            "ref": "",
            "suggested_fix": None,
        }
        rec.update(over)
        out.append(rec)
    return out


def old_in_client(n: int, **over) -> list[dict]:
    """*n* old-shape IN-CLIENT finding dicts (`severity`, `file`, `line`,
    `title`, `body`, `fix` — no `id`, no `rule_name`) — the pre-KLC-127 shape
    code-review/external-review used to emit."""
    out = []
    for i in range(1, n + 1):
        rec = {
            "severity": "high",
            "file": "src/foo.py",
            "line": 10,
            "title": f"title {i}",
            "body": f"body {i}",
            "fix": None,
        }
        rec.update(over)
        out.append(rec)
    return out


def verdict_md(findings: list, decisions: list, *, narrative: str = "",
               one_line: bool = False, newline: str = "\n") -> str:
    """A reviewer's `.md` verdict text: *narrative* followed by one fenced
    ```json block carrying `{"findings": ..., "decisions_to_confirm": ...}`.
    `one_line=True` writes the JSON with no indent (`spec_review`'s own
    D-004 layout-preservation rule reads this as "stays one line");
    otherwise `indent=2`. `newline="\\r\\n"` rewrites every line break in the
    WHOLE text (narrative included) to CRLF, mirroring a real CRLF file."""
    doc = {"findings": findings, "decisions_to_confirm": decisions}
    js = json.dumps(doc, ensure_ascii=False) if one_line else json.dumps(doc, ensure_ascii=False, indent=2)
    body = f"{narrative}\n```json\n{js}\n```\n" if narrative else f"```json\n{js}\n```\n"
    if newline == "\r\n":
        body = body.replace("\n", "\r\n")
    return body


def tree_hashes(root: Path) -> dict:
    """SHA-256 of every file under *root*, keyed by its path relative to
    *root* — used to assert that a dry run / an unchanged ticket / an
    already-migrated corpus is left byte-identical."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# --- step-2 additions (AC-2/AC-10): a real git-backed klc-state checkout ----

import subprocess  # noqa: E402

_ALICE = "alice@example.com"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)})
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def seed_git_state(tmp_path: Path) -> Path:
    """Git-init the `.klc` dir `make_project` already created under
    *tmp_path* (`tmp_path/project/.klc`), commit whatever is already there
    (tickets added so far) and bind it to a bare `sm` remote — the
    CAS-push substrate `state_feature.enabled()` detects (mirrors
    `test_klc111_migrate_vocabulary._seed_git_corpus`). Returns the bare
    remote path; callers needing the local `.klc` dir derive it the same
    way `make_project` does (`tmp_path / "project" / ".klc"`)."""
    klc = tmp_path / "project" / ".klc"
    bound = tmp_path / "sm.git"
    subprocess.run(["git", "init", "--bare", "-b", "klc-state", str(bound)],
                  check=True, capture_output=True)
    _git(klc, "init", "-b", "klc-state")
    _git(klc, "config", "user.email", _ALICE)
    _git(klc, "config", "user.name", "Alice")
    _git(klc, "config", "commit.gpgsign", "false")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")
    _git(klc, "remote", "add", "sm", str(bound))
    _git(klc, "push", "-u", "sm", "klc-state")
    return bound


def remote_commit_count(klc: Path) -> int:
    """The number of commits reachable from *klc*'s current `klc-state`
    HEAD (every push in this test goes through this same local checkout,
    so its own HEAD count equals the bare remote's after a successful
    push)."""
    out = _git(klc, "rev-list", "--count", "HEAD")
    return int(out.strip())


def push_peer_update(bound: Path, tmp_path: Path, rel: str, content: str) -> None:
    """Step-7 (external review F-2): simulate a PEER pushing a straggler
    update directly to the bare remote *bound* — clones it into a
    throwaway dir, writes *rel* (relative to the clone's `.klc` root,
    e.g. `'tickets/KLC-1/x.json'`), commits and pushes, all without
    touching the caller's own worktree. A subsequent `migrate()` only
    sees this if it pulls `klc-state` first."""
    peer = tmp_path / "peer-clone"
    subprocess.run(
        ["git", "clone", "-q", str(bound), str(peer)], check=True,
        capture_output=True, env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(peer)})
    _git(peer, "config", "user.email", "peer@example.com")
    _git(peer, "config", "user.name", "Peer")
    _git(peer, "config", "commit.gpgsign", "false")
    path = peer / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", "peer straggler update")
    _git(peer, "push", "-q", "origin", "HEAD:klc-state")


def listing(tdir: Path) -> set:
    """Every file path under *tdir*, relative to it — used to assert that a
    changed ticket's directory holds no new path other than the audit
    note."""
    return {str(p.relative_to(tdir)) for p in tdir.rglob("*") if p.is_file()}


# --- step-3 additions (AC-12/AC-13/AC-14): the frozen corpus ----------------

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "klc154-corpus"

_CANDIDATE_RELS = (
    "spec-review-findings.json", "spec-review.md",
    "test-plan-review-findings.json", "test-plan-review.md",
    "impl-plan-review-findings.json", "impl-plan-review.md",
    "drift-review-findings.json", "drift-review.md",
    "review/code-review-findings.json", "review/external-review-findings.json",
)

_MD_KIND = {
    "spec-review.md": "spec", "test-plan-review.md": "test-plan",
    "impl-plan-review.md": "impl-plan", "drift-review.md": "drift",
}
_JSON_KIND = {
    "spec-review-findings.json": "spec", "test-plan-review-findings.json": "test-plan",
    "impl-plan-review-findings.json": "impl-plan", "drift-review-findings.json": "drift",
    "code-review-findings.json": "code-review", "external-review-findings.json": "external-review",
}


def materialize_corpus(tickets: Path) -> list:
    """Expand the flat, committed `tests/fixtures/klc154-corpus/` sample
    (`KEY__relpath`, `/` encoded as `--`) into a scratch
    `tickets/<KEY>/<relpath>` tree, writing a synthetic `meta.json` per
    ticket (every ticket archived — the migration itself is proven
    phase-agnostic elsewhere, `test_klc154_real_run.py`). Returns the
    sorted list of ticket keys."""
    keys: set = set()
    for path in sorted(CORPUS.iterdir()):
        if not path.is_file() or path.name == "README.md":
            continue
        key, _, relpath_enc = path.name.partition("__")
        relpath = relpath_enc.replace("--", "/")
        dest = tickets / key / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        keys.add(key)
    for key in keys:
        add_ticket(tickets, key, {})  # writes meta.json only; files already in place
    return sorted(keys)


def _findings_of(path: Path):
    """Every finding dict of *path* — a JSON list as-is, or the `findings`
    of a `.md` verdict's last fenced block (`[]` when there is none)."""
    import findings_migrate
    if path.suffix == ".md":
        span = findings_migrate._verdict_span(path.read_text(encoding="utf-8"))
        return list(span[2].get("findings") or []) if span else []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def snapshot_findings(tickets: Path) -> dict:
    """Per ticket and candidate file: `(finding count, {non-empty ids})` —
    used to assert that a migration run loses no finding and no non-empty
    old id."""
    out: dict = {}
    for tdir in sorted(tickets.iterdir()):
        if not tdir.is_dir() or not (tdir / "meta.json").is_file():
            continue
        files = {}
        for rel in _CANDIDATE_RELS:
            path = tdir / rel
            if not path.is_file():
                continue
            items = _findings_of(path)
            ids = {r.get("id") for r in items if isinstance(r, dict) and r.get("id")}
            files[rel] = (len(items), ids)
        out[tdir.name] = files
    return out


def passes_stored_check(path: Path) -> bool:
    """AC-8: whether *path* (a stored/derived JSON list, or a `.md`
    verdict's findings) passes `handback.validate_findings` for its kind.
    A path this module does not recognise, or a `.md` with no verdict
    block, trivially holds (nothing to check there)."""
    import handback
    kind = _MD_KIND.get(path.name) if path.suffix == ".md" else _JSON_KIND.get(path.name)
    if kind is None:
        return True
    if path.suffix == ".md":
        import findings_migrate
        span = findings_migrate._verdict_span(path.read_text(encoding="utf-8"))
        if span is None:
            return True
        items = list(span[2].get("findings") or [])
    else:
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
    return handback.validate_findings(kind, items) == []


def pool_floor_holds(tickets: Path, key: str) -> bool:
    """D-011: `findings.py pool`'s own pooled `findings[]` (via
    `handback.pool_main`) never holds fewer entries than the largest
    single reviewer's raw (review-kind) list for *key*."""
    import findings as _findings
    import handback
    tdir = tickets / key
    items, _notes = handback.load_ticket_findings(tdir)
    review_items = [f for f in items if f.kind in _findings.REVIEW_KINDS]
    if not review_items:
        return True  # nothing to measure, vacuously holds
    counts: dict = {}
    for f in review_items:
        counts[f.reviewer] = counts.get(f.reviewer, 0) + 1
    largest = max(counts.values())
    handback.pool_main(["--ticket", key])
    pool = json.loads((tdir / "review" / "findings-pool.json").read_text(encoding="utf-8"))
    return len(pool["findings"]) >= largest
