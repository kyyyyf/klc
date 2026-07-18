#!/usr/bin/env python3
"""planning-eval.py — planning-index evaluation harness (KLC-067).

The **measurement layer** of the planning index (planning_indexer.md §"Feedback
loop / eval harness", §"Метрики качества", Rollout step 2). Built metrics-first —
before the retriever (KLC-068) exists — so the later views/edges/roles/retriever
are not tuned blind.

Runs over an archived-ticket corpus and emits
``.klc/index/planning/eval_report.json`` with:

Pre-retriever metrics (computable NOW, no retriever):
  - **module-map coverage**  — files assigned / total files (repo walk).
  - **orphan rate**          — files no module claims / total files.
  - **diff -> affected-modules precision/recall** — for each archived ticket,
    resolve its git-diff's touched files to modules via the ONE resolver
    (``module_membership.file_to_module``, KLC-066) and compare to the ticket's
    recorded ``meta.affected_modules``.

Retriever seam (unavailable until KLC-068):
  - ``recall@5/10``, ``precision@10``, ``mean-files-before-first-edit`` are
    computed from a ticket's ``retrieval_trace.json`` when present, else the
    section reports ``status: "unavailable"`` and the run still exits 0. The
    retrieval-metric keys + the status-gated contract are stable across the two
    states (null when unavailable, numeric when ok), so KLC-068 adds no schema.

CLI (planning_indexer.md §"CLI / API контракты"):
    planning-eval.py --tickets <dir> [--modules <path>] [--repo <path>]
                     [--out <path>]

Exit codes: ``0`` ok (including a degraded run); ``2`` bad argument (``--tickets``
is not a directory). Never hard-fails on a missing optional source — it degrades
and records the reason in ``errors[]`` (like ``dep_graph.py``). ``PROJECT_ROOT``
comes from the environment.

Membership resolution goes ONLY through ``module_membership.file_to_module``; no
private longest-prefix matcher is reintroduced (that would recreate the #1 risk
planning_indexer.md names — a second, divergent module set).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve imports the same way the other skills do: add the project root and the
# skills dir so `module_membership` (the KLC-066 resolver) imports cleanly whether
# the skill is run as a script or loaded by path from a test.
_FILE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _FILE_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_FILE_DIR))
import module_membership as _mm  # noqa: E402  (KLC-066: the one resolver)

REPORT_SCHEMA_VERSION = 1

# Paths never counted as code scope. Ticket lifecycle churn (.klc/) and VCS
# metadata must not inflate the coverage denominator or a ticket's computed
# module set. Mirrors the baseline excludes used by dep_graph.py / file_scanner.
_BASELINE_EXCL = re.compile(
    r"(^|/)(\.git|\.klc|\.claude|node_modules|\.venv|venv|__pycache__|target|"
    r"build|dist|out|bin|obj|\.gradle|\.idea|\.vs|\.next|\.cache|\.serena-cache|"
    r"\.pytest_cache|\.mypy_cache)(/|$)"
)


# --------------------------------------------------------------------------- #
# membership (AC-2 — single resolver, no private matcher)
# --------------------------------------------------------------------------- #
def resolve_modules_for_files(files, modules_data) -> list[str]:
    """Modules touched by *files*, via the KLC-066 resolver. A shared/out-of-path
    file contributes every module in its ``member_of`` so it is never stranded."""
    names: set[str] = set()
    for f in files:
        names.update(_mm.file_to_module(f, modules_data)["member_of"])
    return sorted(names)


def precision_recall(computed, truth):
    """Return (precision, recall, missed, extra) comparing computed vs truth sets.

    precision = |computed ∩ truth| / |computed|   (1.0 by convention when computed
                is empty: nothing was surfaced, so there are no false positives —
                the miss shows up in recall, not as a misleading 0 precision)
    recall    = |computed ∩ truth| / |truth|      (0 when truth empty)
    missed    = truth − computed   (in ground truth, resolver did not surface)
    extra     = computed − truth   (resolver surfaced, not in ground truth)
    """
    c, t = set(computed), set(truth)
    inter = c & t
    prec = len(inter) / len(c) if c else 1.0
    rec = len(inter) / len(t) if t else 0.0
    return prec, rec, sorted(t - c), sorted(c - t)


# --------------------------------------------------------------------------- #
# per-ticket diff derivation
# --------------------------------------------------------------------------- #
def _excluded(path: str) -> bool:
    return bool(_BASELINE_EXCL.search(path)) or not path


def _grep_pattern(key: str) -> str:
    """Word-boundary ERE for a ticket key so `TCK-1`/`KLC-05` does not collide
    with `TCK-11`/`KLC-051`. `-` inside the key is a literal in ERE."""
    return f"(^|[^0-9A-Za-z]){re.escape(key)}([^0-9A-Za-z]|$)"


def _git(args: list[str], repo: Path) -> tuple[int, str]:
    """Run `git <args>` in *repo*; return (returncode, stdout). -1 on OSError."""
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(repo))
    except OSError:
        return -1, ""
    return r.returncode, r.stdout


def git_touched(key: str, repo: Path) -> tuple[list[str], bool]:
    """Return (files_after_exclusion, source_present) for a ticket's commits.

    This is the **best-effort** live path (see docs §Git-derivation caveats); the
    stored-patch seam is authoritative. `source_present` is True iff
    `git log --grep=<key>` (word-bounded) matched at least one commit — reported
    SEPARATELY from the post-exclusion file list so the caller can tell two very
    different cases apart:
      - no matching commit          -> ([], False) — a real derivation gap (skip);
      - commits matched but every    -> ([], True)  — a real 0-footprint evaluation
        changed path was excluded                     (score it, recall 0), NOT a gap.

    Merge commits: `git log --name-only` suppresses merge diffs by default, so a
    key that lands only on a `--no-ff` MERGE would derive no files. Each matched
    merge's first-parent diff (`<sha>^..<sha>` — the files it integrated into the
    target branch, not both sides doubled) is added so merge-only tickets get
    their real footprint instead of a spurious recall-0.
    """
    grep = f"--grep={_grep_pattern(key)}"
    # One probe gives both source-presence and the merge SHAs: `%H %P` prints the
    # commit then its parents; >1 parent == a merge.
    rc, out = _git(["log", "--all", "-E", grep, "--format=%H %P"], repo)
    if rc != 0:
        return [], False
    commits = [ln.split() for ln in out.splitlines() if ln.strip()]
    if not commits:
        return [], False
    merge_shas = [parts[0] for parts in commits if len(parts) > 2]

    files: set[str] = set()
    # Non-merge commits (and the non-suppressed side) via the broad name-only log.
    rc, out = _git(["log", "--all", "-E", grep, "--name-only", "--pretty=format:"], repo)
    if rc == 0:
        files |= {ln.strip() for ln in out.splitlines() if ln.strip()}
    # Merge augmentation: first-parent diff of each matched merge commit.
    for sha in merge_shas:
        rc, out = _git(["diff-tree", "--no-commit-id", "--name-only", "-r",
                        f"{sha}^", sha], repo)
        if rc == 0:
            files |= {ln.strip() for ln in out.splitlines() if ln.strip()}

    return sorted(f for f in files if not _excluded(f)), True


def stored_patch_files(ticket_dir: Path) -> list[str] | None:
    """Deterministic fixture/offline seam: if a ticket dir carries a stored diff
    (`*.patch` / `*.diff`) or `changed_files.txt`, use it instead of git. Returns
    None when no stored source is present (caller falls back to git)."""
    changed = ticket_dir / "changed_files.txt"
    if changed.exists():
        return sorted(
            f.strip() for f in changed.read_text(encoding="utf-8").splitlines()
            if f.strip() and not _excluded(f.strip())
        )
    patches = sorted(list(ticket_dir.glob("*.patch")) + list(ticket_dir.glob("*.diff")))
    if not patches:
        return None
    files: set[str] = set()
    for patch in patches:
        for ln in patch.read_text(encoding="utf-8", errors="ignore").splitlines():
            # Added/modified files carry `+++ b/<path>`; a deletion emits
            # `+++ /dev/null`, so the deleted path is captured from `--- a/<path>`.
            if ln.startswith("+++ b/"):
                files.add(ln[6:].strip())
            elif ln.startswith("--- a/"):
                files.add(ln[6:].strip())
    return sorted(f for f in files if f and f != "/dev/null" and not _excluded(f))


def ticket_touched_files(key: str, ticket_dir: Path, repo: Path) -> tuple[list[str], bool, str]:
    """Return (files_after_exclusion, source_present, source_kind) for a ticket.

    source_kind is the diff-derivation seam:
      - "stored-patch"  — a `changed_files.txt` / `*.patch` in the ticket dir.
        AUTHORITATIVE and deterministic; wins when present (even if it resolves to
        no in-scope files: a 0-footprint evaluation, not a derivation gap).
      - "git-log-grep"  — derived from git history by key. BEST-EFFORT (see the
        caveats: merge/squash/cross-key-mention/`--all`-widening).
      - "none"          — no source found at all (a real derivation gap)."""
    stored = stored_patch_files(ticket_dir)
    if stored is not None:
        return stored, True, "stored-patch"
    files, present = git_touched(key, repo)
    return files, present, ("git-log-grep" if present else "none")


# --------------------------------------------------------------------------- #
# coverage / orphan rate
# --------------------------------------------------------------------------- #
def is_git_repo(repo: Path) -> bool:
    """True iff *repo* is inside a git work tree. A bad `--repo` must degrade the
    coverage + diff sections, not be silently reported as valid zeros."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True,
        )
    except OSError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def _walk_repo_files(repo: Path) -> list[str]:
    """Repo-relative POSIX paths of code files, applying baseline excludes.
    structural.json carries only counts, so the coverage denominator is a walk.

    Uses os.walk with in-place pruning of excluded directories so the walk never
    descends into `.git` / nested `.claude/worktrees` (a real-repo perf cliff)."""
    import os
    out: list[str] = []
    for dirpath, dirs, files in os.walk(repo):
        rel_dir = Path(dirpath).relative_to(repo).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirs[:] = [d for d in dirs if not _excluded(prefix + d)]
        for fn in files:
            rel = prefix + fn
            if _excluded(rel):
                continue
            out.append(rel)
    return out


def compute_coverage(files: list[str], modules_data) -> dict:
    total = len(files)
    assigned = orphan = shared = 0
    for f in files:
        res = _mm.file_to_module(f, modules_data)
        if res["resolution_source"] == "orphan":
            orphan += 1
        else:
            assigned += 1
            if res["is_shared"]:
                shared += 1
    return {
        "status": "ok",
        "files_total": total,
        "files_assigned": assigned,
        "files_orphan": orphan,
        "files_shared": shared,
        "coverage_ratio": (assigned / total) if total else 0.0,
        "orphan_rate": (orphan / total) if total else 0.0,
    }


# --------------------------------------------------------------------------- #
# retrieval-metrics seam (KLC-068 populates the traces)
# --------------------------------------------------------------------------- #
def _retrieval_for_ticket(trace: dict, relevant: set[str]) -> dict | None:
    """Per-ticket retrieval metrics from a retrieval_trace.json. `relevant` is the
    set of files the ticket actually changed (ground truth for recall). Returns
    None when the trace has no usable candidate ranking."""
    candidates = [c for c in (trace.get("files_to_read_first") or []) if c]
    if not candidates or not relevant:
        return None

    def recall_at(n: int) -> float:
        topn = set(candidates[:n])
        return len(topn & relevant) / len(relevant)

    top10 = set(candidates[:10])
    precision_at_10 = len(top10 & relevant) / min(10, len(candidates))
    first = next((i for i, f in enumerate(candidates, 1) if f in relevant), None)
    files_before_first_edit = (first - 1) if first is not None else len(candidates)
    return {
        "recall_at_5": recall_at(5),
        "recall_at_10": recall_at(10),
        "precision_at_10": precision_at_10,
        "files_before_first_edit": files_before_first_edit,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# --------------------------------------------------------------------------- #
# report assembly
# --------------------------------------------------------------------------- #
def _iter_ticket_dirs(tickets_root: Path):
    for d in sorted(tickets_root.iterdir()):
        if d.is_dir() and (d / "meta.json").exists():
            yield d


def _generated_at() -> str:
    """Reproducible when SOURCE_DATE_EPOCH is set (byte-stable reports for CI /
    diffing); wall-clock otherwise."""
    import os
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            return datetime.fromtimestamp(int(epoch), timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return datetime.now(timezone.utc).isoformat()


def build_report(tickets_root: Path, modules_data, repo: Path,
                 errors: list[str]) -> dict:
    report: dict = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _generated_at(),
        "tickets_root": str(tickets_root),
        "repo": str(repo),
        "corpus": {"tickets_total": 0, "tickets_evaluated": 0, "tickets_skipped": []},
        "coverage": {"status": "unavailable", "reason": ""},
        "diff_affected_modules": {"status": "unavailable", "reason": ""},
        "retrieval_metrics": {
            "status": "unavailable", "reason": "",
            "recall_at_5": None, "recall_at_10": None,
            "precision_at_10": None, "mean_files_before_first_edit": None,
            "per_ticket": [],
        },
        "errors": errors,
    }

    # Validate the data source. A bad --repo (not a git checkout, or a walk that
    # yields zero files) must degrade coverage + diff to 'unavailable' + errors[],
    # NOT be reported as a valid 'ok' section full of zeros / 0-precision.
    repo_files: list[str] = _walk_repo_files(repo) if repo.is_dir() else []
    repo_is_git = is_git_repo(repo)
    repo_ok = repo_is_git and len(repo_files) > 0
    if not repo_ok:
        reason = (
            f"--repo {repo} is not a git checkout"
            if not repo_is_git else
            f"--repo {repo} walk yielded no files"
        )
        errors.append(f"{reason}; coverage + diff metrics degraded")

    diff_enabled = (modules_data is not None) and repo_ok

    # --- coverage / orphan rate (needs modules.json AND a valid repo walk) ---
    if modules_data is None:
        report["coverage"] = {"status": "unavailable", "reason": "modules.json unavailable"}
    elif not repo_ok:
        report["coverage"] = {"status": "unavailable", "reason": reason}
    else:
        report["coverage"] = compute_coverage(repo_files, modules_data)

    ticket_dirs = list(_iter_ticket_dirs(tickets_root))
    report["corpus"]["tickets_total"] = len(ticket_dirs)

    per_ticket: list[dict] = []
    skipped: list[dict] = []
    retrieval_rows: list[dict] = []

    prec_sum = rec_sum = 0.0
    micro_inter = micro_computed = micro_truth = 0

    for d in ticket_dirs:
        key = d.name
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append({"ticket": key, "reason": f"unreadable meta.json: {exc}"})
            continue
        truth = meta.get("affected_modules") or []

        touched, source_present, source_kind = ticket_touched_files(key, d, repo)
        relevant = set(touched)
        confidence = "authoritative" if source_kind == "stored-patch" else "best-effort"

        # diff -> affected-modules (needs modules.json + valid repo + non-empty truth)
        if diff_enabled:
            if not truth:
                skipped.append({"ticket": key, "reason": "meta.affected_modules is empty"})
            elif not source_present:
                # No matching commit AND no stored patch: a real diff-DERIVATION gap
                # (e.g. a squash / PR-merge that dropped the key from the subject).
                # Skip so it never tanks the aggregate — a git no-match and an empty
                # git result are indistinguishable, but here NO source was found.
                skipped.append({"ticket": key,
                                "reason": "no matching commits / no stored patch (diff-derivation gap)"})
            else:
                # A source EXISTED. Even if every changed path was excluded (a
                # lifecycle-only ticket -> empty footprint), this is a REAL 0-recall
                # evaluation: score it with computed=[]; do NOT mask it as a gap.
                computed = resolve_modules_for_files(touched, modules_data)
                prec, rec, missed, extra = precision_recall(computed, truth)
                per_ticket.append({
                    "ticket": key,
                    "truth": sorted(set(truth)),
                    "computed": computed,
                    "matched": sorted(set(computed) & set(truth)),
                    "missed": missed,
                    "extra": extra,
                    "precision": prec,
                    "recall": rec,
                    "files_touched": len(touched),
                    "derivation_source": source_kind,       # stored-patch | git-log-grep
                    "derivation_confidence": confidence,    # authoritative | best-effort
                })
                prec_sum += prec
                rec_sum += rec
                inter = len(set(computed) & set(truth))
                micro_inter += inter
                micro_computed += len(set(computed))
                micro_truth += len(set(truth))

        # retrieval seam
        trace_path = d / "retrieval_trace.json"
        if trace_path.exists():
            try:
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                row = _retrieval_for_ticket(trace, relevant)
            except (OSError, json.JSONDecodeError):
                row = None
            if row is None:
                skipped.append({"ticket": key,
                                "reason": "retrieval_trace.json unusable (no candidates or no edits)"})
            else:
                row["ticket"] = key
                retrieval_rows.append(row)

    report["corpus"]["tickets_evaluated"] = len(per_ticket)
    report["corpus"]["tickets_skipped"] = skipped

    # --- diff -> affected-modules section ---
    if modules_data is None:
        report["diff_affected_modules"] = {
            "status": "unavailable", "reason": "modules.json unavailable",
            "per_ticket": [],
        }
    elif not repo_ok:
        report["diff_affected_modules"] = {
            "status": "unavailable", "reason": reason, "per_ticket": [],
        }
    elif not per_ticket:
        report["diff_affected_modules"] = {
            "status": "unavailable",
            "reason": "no tickets with a non-empty meta.affected_modules and a derivable diff",
            "per_ticket": [],
        }
    else:
        n = len(per_ticket)
        authoritative = sum(1 for t in per_ticket if t["derivation_source"] == "stored-patch")
        best_effort = n - authoritative
        report["diff_affected_modules"] = {
            "status": "ok",
            "mean_precision": prec_sum / n,
            "mean_recall": rec_sum / n,
            "micro_precision": (micro_inter / micro_computed) if micro_computed else 0.0,
            "micro_recall": (micro_inter / micro_truth) if micro_truth else 0.0,
            "tickets": n,
            "authoritative_tickets": authoritative,
            "best_effort_tickets": best_effort,
            "note": (
                "derivation_source per ticket: 'stored-patch' is authoritative; "
                "'git-log-grep' is best-effort (merge / squash / cross-key-mention / "
                "--all-widening). For authoritative recall/precision, give each ticket "
                "a changed_files.txt or *.patch."
            ),
            "per_ticket": per_ticket,
        }

    # --- retrieval section ---
    if retrieval_rows:
        report["retrieval_metrics"] = {
            "status": "ok",
            "recall_at_5": _mean([r["recall_at_5"] for r in retrieval_rows]),
            "recall_at_10": _mean([r["recall_at_10"] for r in retrieval_rows]),
            "precision_at_10": _mean([r["precision_at_10"] for r in retrieval_rows]),
            "mean_files_before_first_edit": _mean(
                [r["files_before_first_edit"] for r in retrieval_rows]),
            "tickets": len(retrieval_rows),
            "per_ticket": retrieval_rows,
        }
    else:
        report["retrieval_metrics"]["reason"] = (
            "no usable retrieval_trace.json in corpus — KLC-068 (the retriever) "
            "will populate per-ticket traces; recall@N/precision@10 plug in then"
        )

    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    import os

    def _default_index() -> Path:
        root = os.environ.get("PROJECT_ROOT")
        base = Path(root).resolve() if root else _PROJECT_ROOT.parent
        return base / ".klc" / "index"

    idx = _default_index()
    ap = argparse.ArgumentParser(description="planning-index eval harness (KLC-067)")
    ap.add_argument("--tickets", type=Path, default=idx.parent / "tickets",
                    help="ticket-archive directory (subdirs with meta.json)")
    ap.add_argument("--modules", type=Path, default=idx / "modules.json",
                    help="modules.json (membership map)")
    ap.add_argument("--repo", type=Path,
                    default=Path(os.environ.get("PROJECT_ROOT") or _PROJECT_ROOT.parent),
                    help="git repo root for diff derivation + coverage walk")
    ap.add_argument("--out", type=Path, default=idx / "planning" / "eval_report.json",
                    help="output report path ('-' for stdout)")
    args = ap.parse_args(argv)

    # Bad argument: --tickets is not a directory -> exit 2 (like file_scanner.py).
    if not args.tickets.is_dir():
        sys.stderr.write(f"planning-eval: --tickets {args.tickets} is not a directory\n")
        return 2

    errors: list[str] = []

    # Missing optional source -> degrade, record in errors[], do NOT hard-fail.
    modules_data = None
    if args.modules.exists():
        try:
            modules_data = json.loads(args.modules.read_text(encoding="utf-8"))
            if isinstance(modules_data, list):
                modules_data = {"modules": modules_data}
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"modules.json unreadable ({exc}); coverage + diff metrics degraded")
            modules_data = None
    else:
        errors.append(f"modules.json not found at {args.modules}; coverage + diff metrics degraded")

    report = build_report(args.tickets, modules_data, args.repo, errors)
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"

    if str(args.out) == "-":
        sys.stdout.write(payload)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        sys.stderr.write(f"planning-eval: wrote {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
