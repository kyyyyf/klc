"""tests/integration/test_klc149_baseline_republish.py — KLC-149 steps 2-5.

Collects every test for the re-published KLC-110 baseline doc: the
docstring/architecture-doc wording (step-2, AC-13), the shared population
summary and the three-column comparison renderer (step-3, AC-8/AC-9/AC-10),
`baseline_compare.py record`/`main` (step-4, AC-9/AC-12/AC-14), and the
final re-published doc itself (step-5, AC-8/AC-9/AC-11/AC-12/AC-14).

`baseline_compare` is imported INSIDE each test that needs it (lazy import,
D-212 in impl-plan.md), never at module top, so the step-2 tests collect and
pass before step-3 creates the module.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "core" / "skills" / "planning-eval.py"
_ARCH_DOC = _FW_ROOT / "docs" / "architecture.md"
_BASELINE_DOC = _FW_ROOT / "docs" / "20260920_klc110-retrieval-baseline.md"
_BASELINE_D = _FW_ROOT / "docs" / "20260920_klc110-retrieval-baseline.d"


def _load_planning_eval():
    spec = importlib.util.spec_from_file_location("planning_eval_klc149_republish", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# step-2 — docstrings, architecture.md, the diff_affected_modules note
# --------------------------------------------------------------------------- #
def test_git_touched_and_ticket_touched_files_docstrings_name_state_exclusion():
    """AC-13: `git_touched.__doc__` and `ticket_touched_files.__doc__` each
    name the state-branch exclusion rule and `integrate_ground_truth`, and
    neither contains `--all` or `Git-derivation caveats`."""
    pe = _load_planning_eval()
    for doc in (pe.git_touched.__doc__, pe.ticket_touched_files.__doc__):
        assert "STATE_BRANCH" in doc
        assert "integrate_ground_truth" in doc
        assert "--all" not in doc
        assert "Git-derivation caveats" not in doc


def test_architecture_doc_has_offline_ground_truth_subsection():
    """AC-13: `docs/architecture.md` gains a named offline-ground-truth
    subsection inside `## Retrieval scoring (KLC-108)`, stating which refs
    are walked, why, and how the offline derivation differs from
    `integrate_ground_truth` (both path filters named); no `--all` anywhere
    in that subsection."""
    text = _ARCH_DOC.read_text(encoding="utf-8")
    start_marker = "### Offline ground truth (KLC-149)"
    assert start_marker in text
    start = text.index(start_marker)
    # The subsection must live inside "## Retrieval scoring (KLC-108)".
    parent_marker = "## Retrieval scoring (KLC-108)"
    assert parent_marker in text
    parent_start = text.index(parent_marker)
    assert parent_start < start

    rest = text[start:]
    next_h2 = rest.find("\n## ", 1)
    subsection = rest if next_h2 == -1 else rest[:next_h2]

    assert "branch" in subsection
    assert "remote-tracking" in subsection
    assert "tags" in subsection
    assert "state branch" in subsection
    assert "integrate_ground_truth" in subsection
    assert "_BASELINE_EXCL" in subsection
    assert ".klc/" in subsection
    assert "--all" not in subsection


def test_diff_affected_modules_note_no_longer_says_all_widening():
    """AC-13 (review F-3 fix): `build_report`'s `diff_affected_modules.note`
    string — the SAME `git_touched`/`ticket_touched_files` derivation,
    surfaced through the module-coverage report — no longer contains the
    literal `--all` and names the code-ref rule."""
    pe = _load_planning_eval()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo,
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo,
                       check=True, capture_output=True)
        (repo / "core" / "intake").mkdir(parents=True)
        (repo / "core" / "intake" / "parser.py").write_text("x=1\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "KLC-9100 step-1: intake parser"],
                       cwd=repo, check=True, capture_output=True)

        modules_data = {"modules": [{"name": "intake", "path": "core/intake/"}], "files": {}}
        tickets_root = repo / ".klc" / "tickets"
        d = tickets_root / "KLC-9100"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"ticket": "KLC-9100",
                                                  "affected_modules": ["intake"]}))

        report = pe.build_report(tickets_root, modules_data, repo, [])
        note = report["diff_affected_modules"]["note"]
        assert "--all" not in note
        assert "code ref" in note

# --------------------------------------------------------------------------- #
# step-3 — population_summary, baseline_compare render pieces
# --------------------------------------------------------------------------- #
def _rows(source: str, n_ok: int, n_unavailable: int) -> list[dict]:
    rows = []
    for i in range(n_ok):
        rows.append({"ticket": f"T-{i}", "trace_source": source, "status": "ok",
                     "derivation_source": "stored-patch",
                     "precision_at_5": 0.5, "recall_at_10": 0.25})
    for i in range(n_unavailable):
        rows.append({"ticket": f"U-{i}", "trace_source": source, "status": "unavailable",
                     "derivation_source": "none"})
    return rows


def test_per_ticket_row_carries_old_and_corrected_side_by_side():
    """AC-10: one row per (ticket, trace_source) with old/corrected status,
    derivation_source, precision@5 and recall@10 in adjacent columns."""
    from core.skills import baseline_compare as bc

    old = {"label": "old", "code_commit": "aaa", "index_generation": "gen-1",
          "rows": {"stored": [
              {"ticket": "KLC-1", "trace_source": "stored", "status": "ok",
               "derivation_source": "git-log-grep", "precision_at_5": 0.5,
               "recall_at_10": 0.25},
          ]}}
    corrected = {"label": "corrected", "code_commit": "bbb", "index_generation": "gen-1",
                "rows": {"stored": [
                    {"ticket": "KLC-1", "trace_source": "stored", "status": "unavailable",
                     "derivation_source": "none"},
                ]}}
    rows = bc.per_ticket_rows(old, corrected)
    assert len(rows) == 1
    row = rows[0]
    assert row["ticket"] == "KLC-1"
    assert row["trace_source"] == "stored"
    assert row["old_status"] == "ok"
    assert row["corrected_status"] == "unavailable"
    assert row["old_derivation_source"] == "git-log-grep"
    assert row["corrected_derivation_source"] == "none"
    assert row["old_precision_at_5"] == 0.5
    assert row["old_recall_at_10"] == 0.25


def test_changed_flag_set_on_status_or_derivation_source_delta():
    """AC-10: a `stored` row that stays `unavailable` but moves
    `git-log-grep` -> `none` is flagged, a status change is flagged, and an
    unchanged pair is not."""
    from core.skills import baseline_compare as bc

    old = {"label": "old", "code_commit": "aaa", "index_generation": "gen-1",
          "rows": {"stored": [
              {"ticket": "KLC-1", "trace_source": "stored", "status": "ok",
               "derivation_source": "git-log-grep"},
              {"ticket": "KLC-2", "trace_source": "stored", "status": "unavailable",
               "derivation_source": "git-log-grep"},
              {"ticket": "KLC-3", "trace_source": "stored", "status": "ok",
               "derivation_source": "stored-patch"},
          ]}}
    corrected = {"label": "corrected", "code_commit": "bbb", "index_generation": "gen-1",
                "rows": {"stored": [
                    {"ticket": "KLC-1", "trace_source": "stored", "status": "unavailable",
                     "derivation_source": "none"},
                    {"ticket": "KLC-2", "trace_source": "stored", "status": "unavailable",
                     "derivation_source": "none"},
                    {"ticket": "KLC-3", "trace_source": "stored", "status": "ok",
                     "derivation_source": "stored-patch"},
                ]}}
    rows = {r["ticket"]: r for r in bc.per_ticket_rows(old, corrected)}
    assert rows["KLC-1"]["changed"] is True       # status changed
    assert rows["KLC-2"]["changed"] is True       # derivation_source changed, status didn't
    assert rows["KLC-3"]["changed"] is False       # nothing changed


def test_summary_table_has_three_columns_per_population_on_fixture_inputs():
    """AC-8: the `### stored` and `### replayed` tables carry the
    three-column header and the five metric rows."""
    from core.skills import baseline_compare as bc

    published_text = (
        "# KLC-110 retrieval baseline\n\n"
        "- measured: 2026-09-25T00:00:00+00:00\n"
        "- index generation: pub-gen\n\n"
        "## stored\n\n"
        "- tickets total: 2\n- tickets scored: 1\n- tickets unavailable: 1\n"
        "- precision@5 mean: 0.5\n- recall@10 mean: 0.25\n\n"
        "| ticket | status | confidence | derivation_source | "
        "derivation_confidence | precision@5 | recall@10 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| KLC-1 | ok |  | stored-patch |  | 0.5 | 0.25 |\n\n"
        "## replayed\n\n"
        "- tickets total: 2\n- tickets scored: 1\n- tickets unavailable: 1\n"
        "- precision@5 mean: 0.5\n- recall@10 mean: 0.25\n\n"
        "| ticket | status | confidence | derivation_source | "
        "derivation_confidence | precision@5 | recall@10 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| KLC-1 | ok |  | stored-patch |  | 0.5 | 0.25 |\n\n"
    )
    old = {"label": "old", "code_commit": "aaa", "index_generation": "gen-1",
          "rows": {"stored": _rows("stored", 1, 1), "replayed": _rows("replayed", 1, 1)}}
    corrected = {"label": "corrected", "code_commit": "bbb", "index_generation": "gen-1",
                "rows": {"stored": _rows("stored", 1, 1), "replayed": _rows("replayed", 1, 1)}}

    out = bc.render_comparison(published_text, "1e4a3734:docs/x.md", old, corrected)
    for source in ("stored", "replayed"):
        assert f"### {source}" in out
    header = ("| metric | published 2026-09-25 | old ground truth, today | "
             "corrected ground truth, today |")
    assert out.count(header) == 2
    for label in ("tickets total", "tickets scored", "tickets unavailable",
                 "precision@5 mean", "recall@10 mean"):
        assert f"| {label} |" in out


def test_header_reports_published_measured_index_generation_and_availability_per_column():
    """external review F-4: the generated header carries the PUBLISHED
    column's own measured time and index generation (parsed from the
    snapshot, not silently dropped), plus one availability line per
    population per column — three columns (published/old/corrected) times
    each rendered population — so the doc intro's claim that the header
    lists 'measured times, index generation, corpus count, availability per
    population' is actually true of the generated bytes."""
    from core.skills import baseline_compare as bc

    published_text = (
        "# KLC-110 retrieval baseline\n\n"
        "- measured: 2026-09-25T00:00:00+00:00\n"
        "- index generation: pub-gen-1\n\n"
        "## stored\n\n"
        "- tickets total: 2\n- tickets scored: 1\n- tickets unavailable: 1\n"
        "- precision@5 mean: 0.5\n- recall@10 mean: 0.25\n\n"
        "| ticket | status | confidence | derivation_source | "
        "derivation_confidence | precision@5 | recall@10 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| KLC-1 | ok |  | stored-patch |  | 0.5 | 0.25 |\n\n"
        "## replayed\n\n"
        "- tickets total: 2\n- tickets scored: 1\n- tickets unavailable: 1\n"
        "- precision@5 mean: 0.5\n- recall@10 mean: 0.25\n\n"
        "| ticket | status | confidence | derivation_source | "
        "derivation_confidence | precision@5 | recall@10 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| KLC-1 | ok |  | stored-patch |  | 0.5 | 0.25 |\n\n"
    )
    old = {"label": "old", "code_commit": "aaa", "measured": "2026-10-02T00:00:00+00:00",
          "index_generation": "gen-1",
          "rows": {"stored": _rows("stored", 1, 1), "replayed": _rows("replayed", 1, 1)}}
    corrected = {"label": "corrected", "code_commit": "bbb",
                "measured": "2026-10-02T00:30:00+00:00", "index_generation": "gen-1",
                "rows": {"stored": _rows("stored", 1, 1), "replayed": _rows("replayed", 1, 1)}}

    out = bc.render_comparison(published_text, "1e4a3734:docs/x.md", old, corrected)
    header = out.split(bc.BEGIN_MARK, 1)[1].split("### stored", 1)[0]

    assert "2026-09-25T00:00:00+00:00" in header
    assert "pub-gen-1" in header
    for source in ("stored", "replayed"):
        for column in ("published 2026-09-25", "old ground truth, today",
                       "corrected ground truth, today"):
            assert f"{source} availability ({column})" in header, (
                f"missing {source!r}/{column!r} availability line in header:\n{header}")


def test_parse_backfill_md_fails_closed_on_missing_field():
    """AC-9: a table text missing `- index generation:` or one summary
    bullet raises `ValueError`."""
    from core.skills import baseline_compare as bc

    missing_index_gen = (
        "# KLC-110 retrieval baseline\n\n- measured: 2026-09-25T00:00:00+00:00\n\n"
        "## stored\n\n- tickets total: 1\n- tickets scored: 1\n"
        "- tickets unavailable: 0\n- precision@5 mean: 0.5\n- recall@10 mean: 0.25\n\n"
    )
    try:
        bc.parse_backfill_md(missing_index_gen)
        assert False, "expected ValueError"
    except ValueError:
        pass

    missing_bullet = (
        "# KLC-110 retrieval baseline\n\n- measured: 2026-09-25T00:00:00+00:00\n"
        "- index generation: gen-1\n\n"
        "## stored\n\n- tickets total: 1\n- tickets scored: 1\n"
        "- precision@5 mean: 0.5\n- recall@10 mean: 0.25\n\n"
    )
    try:
        bc.parse_backfill_md(missing_bullet)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_render_refuses_runs_with_different_index_generation_or_corpus():
    """AC-9/A-001: different `index_generation` values, or different ticket
    sets, raise `ValueError`."""
    from core.skills import baseline_compare as bc

    published_text = (
        "# KLC-110 retrieval baseline\n\n- measured: 2026-09-25T00:00:00+00:00\n"
        "- index generation: pub-gen\n\n"
        "## stored\n\n- tickets total: 0\n- tickets scored: 0\n"
        "- tickets unavailable: 0\n- precision@5 mean: null\n- recall@10 mean: null\n\n"
    )
    old = {"label": "old", "code_commit": "aaa", "index_generation": "gen-1",
          "rows": {"stored": _rows("stored", 1, 0)}}
    corrected_diff_gen = {"label": "corrected", "code_commit": "bbb",
                         "index_generation": "gen-2",
                         "rows": {"stored": _rows("stored", 1, 0)}}
    try:
        bc.render_comparison(published_text, "spec", old, corrected_diff_gen)
        assert False, "expected ValueError"
    except ValueError:
        pass

    corrected_diff_set = {"label": "corrected", "code_commit": "bbb",
                         "index_generation": "gen-1",
                         "rows": {"stored": _rows("stored", 1, 0) + [
                             {"ticket": "EXTRA", "trace_source": "stored",
                              "status": "unavailable", "derivation_source": "none"}]}}
    try:
        bc.render_comparison(published_text, "spec", old, corrected_diff_set)
        assert False, "expected ValueError"
    except ValueError:
        pass


_MIN_PUBLISHED_TEXT = (
    "# Doc\n\n"
    "- measured: 2026-01-01T00:00:00+00:00\n"
    "- index generation: pub-gen\n\n"
    "## stored\n\n"
    "- tickets total: 1\n- tickets scored: 1\n- tickets unavailable: 0\n"
    "- precision@5 mean: 0.5\n- recall@10 mean: 0.25\n\n"
    "| ticket | status | confidence | derivation_source | "
    "derivation_confidence | precision@5 | recall@10 |\n"
    "|---|---|---|---|---|---|---|\n"
    "| KLC-1 | ok |  | stored-patch |  | 0.5 | 0.25 |\n\n"
)


def test_splice_refuses_missing_or_duplicate_markers():
    """AC-9: no marker, or two `BEGIN_MARK`s, raise `ValueError`; a correct
    doc is spliced and a second splice is a byte no-op. step-7 (external
    review F-2): the idempotency check now splices `render_comparison`'s
    REAL output, which ends in its own newline — the old bug (each splice
    appending one more blank line) only showed up on a block that did; the
    hand-written literal this test used before ended with no newline at
    all, which is exactly why it never caught the bug."""
    from core.skills import baseline_compare as bc

    no_marker = "# Doc\n\nprose only\n"
    try:
        bc.splice_generated(no_marker, "block text\n")
        assert False, "expected ValueError"
    except ValueError:
        pass

    dup = (f"# Doc\n\n{bc.BEGIN_MARK}\nold\n{bc.END_MARK}\n\n"
          f"{bc.BEGIN_MARK}\nold2\n{bc.END_MARK}\n")
    try:
        bc.splice_generated(dup, "block text\n")
        assert False, "expected ValueError"
    except ValueError:
        pass

    old_run = {"label": "old", "code_commit": "aaa", "index_generation": "gen-1",
              "rows": {"stored": _rows("stored", 1, 0)}}
    corrected_run = {"label": "corrected", "code_commit": "bbb", "index_generation": "gen-1",
                    "rows": {"stored": _rows("stored", 1, 0)}}
    block = bc.render_comparison(_MIN_PUBLISHED_TEXT, "spec", old_run, corrected_run)
    assert block.endswith("\n") and not block.endswith("\n\n"), (
        "the real render output ends in exactly one newline — the shape that "
        "exposed F-2")

    doc = f"# Doc\n\n{bc.BEGIN_MARK}\nold\n{bc.END_MARK}\n\n"
    once = bc.splice_generated(doc, block)
    assert bc.BEGIN_MARK in once
    assert "\nold\n" not in once
    twice = bc.splice_generated(once, block)
    assert once == twice


def test_render_cli_rerun_on_a_doc_copy_is_byte_identical(tmp_path):
    """step-7 (external review F-2): the shipped `render` CLI, run TWICE in
    a row against the SAME `--doc` path (a throwaway copy, never the live
    doc) with the SAME three committed inputs, produces byte-identical
    files both times — no blank-line growth from a second render, which is
    exactly the shape that regressed the real doc in step-6."""
    doc_copy = tmp_path / "doc.md"
    doc_copy.write_text(_BASELINE_DOC.read_text(encoding="utf-8"), encoding="utf-8")

    argv = [sys.executable, str(_FW_ROOT / "core" / "skills" / "baseline_compare.py"),
           "render",
           "--published", str(_BASELINE_D / "published-1e4a3734.md"),
           "--published-source", "1e4a3734:docs/20260920_klc110-retrieval-baseline.md",
           "--old", str(_BASELINE_D / "old.json"),
           "--corrected", str(_BASELINE_D / "corrected.json"),
           "--doc", str(doc_copy)]

    r1 = subprocess.run(argv, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    after_first = doc_copy.read_bytes()

    r2 = subprocess.run(argv, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    after_second = doc_copy.read_bytes()

    assert after_first == after_second


def test_population_summary_matches_render_backfill_bullets():
    """AC-9: for a fixture population, the bullets `render_backfill` prints
    equal the values of `population_summary` (fails before GREEN only
    because `population_summary` does not exist yet)."""
    pe = _load_planning_eval()
    rows = _rows("stored", 2, 1)
    summary = pe.population_summary(rows)
    rendered = pe.render_backfill({"stored": rows}, "gen-1")
    assert f"- tickets total: {summary['total']}" in rendered
    assert f"- tickets scored: {summary['scored']}" in rendered
    assert f"- tickets unavailable: {summary['unavailable']}" in rendered
    assert f"- precision@5 mean: {summary['precision_at_5_mean']}" in rendered
    assert f"- recall@10 mean: {summary['recall_at_10_mean']}" in rendered
# --------------------------------------------------------------------------- #
# step-4 — record a "today" run from a given code tree
# --------------------------------------------------------------------------- #
def _write_hermetic_corpus(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True,
                   capture_output=True)
    # KLC-149 step-7 (external review F-3): the stand-in changed file lives
    # OUTSIDE core/ on purpose. The widened code-commit check now compares
    # a code tree's WHOLE core/ subtree against a commit's core/ tree, so a
    # throwaway file committed only here, under core/, would always read as
    # "present in the repo's commit but not in the code tree" once a test
    # points --code-dir at a REAL code tree (`_FW_ROOT` or a stub) that has
    # no such file.
    (repo / "app").mkdir()
    (repo / "app" / "a.py").write_text("x=1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "KLC-X step-1: seed"], cwd=repo, check=True,
                   capture_output=True)

    tickets_root = repo / ".klc" / "tickets"
    d = tickets_root / "KLC-X"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"ticket": "KLC-X", "affected_modules": []}))
    (d / "changed_files.txt").write_text("app/a.py\n")

    index_dir = repo / ".klc" / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "modules.json").write_text(json.dumps({"modules": [], "generated_at": "gen-1"}))

    return {"repo": repo, "tickets_root": tickets_root, "index_dir": index_dir,
           "modules": index_dir / "modules.json"}


def _hash_tree(root: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    if not root.exists():
        return "absent"
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


def test_backfill_cli_writes_only_to_out_and_out_md_paths(tmp_path):
    """AC-12 (pin): `planning-eval.py --backfill` with explicit
    `--tickets/--modules/--index/--repo` and `--out`/`--out-md` under a
    SEPARATE tmp_path dir changes nothing under the stand-in `.klc/`."""
    fx = _write_hermetic_corpus(tmp_path)
    before_tickets = _hash_tree(fx["tickets_root"])
    before_index = _hash_tree(fx["index_dir"])

    work = tmp_path / "work"
    out = work / "out.json"
    out_md = work / "out.md"
    r = subprocess.run(
        [sys.executable, str(_SKILL), "--backfill", "--trace-source", "stored",
         "--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
         "--index", str(fx["index_dir"]), "--repo", str(fx["repo"]),
         "--out", str(out), "--out-md", str(out_md)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    after_tickets = _hash_tree(fx["tickets_root"])
    after_index = _hash_tree(fx["index_dir"])
    assert before_tickets == after_tickets
    assert before_index == after_index
    assert out.exists()
    assert out_md.exists()


def _record_code_commit(repo: Path, script_bytes: bytes) -> str:
    """Commit *script_bytes* into *repo* at `core/skills/planning-eval.py`
    and return the resulting commit sha — a `code_commit` that `record_run`'s
    blob check (external review F-1) accepts for a `code_dir` whose own
    `planning-eval.py` holds the SAME bytes."""
    dest = repo / "core" / "skills" / "planning-eval.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(script_bytes)
    subprocess.run(["git", "add", "-f", "core/skills/planning-eval.py"], cwd=repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "snapshot code for record_run commit check"],
                   cwd=repo, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def _mirror_fw_core_commit(repo: Path) -> str:
    """Mirror `_FW_ROOT`'s WHOLE `core/` subtree into *repo* and commit it,
    returning the resulting sha (KLC-149 step-7, external review F-3: the
    code-commit check now compares every file under `core/`, blob for
    blob, so a `code_commit` that must be ACCEPTED for `--code-dir
    _FW_ROOT` needs a commit whose `core/` tree is a byte-exact copy of
    `_FW_ROOT`'s own `core/`, not just one file). `__pycache__` and
    `.pyc`/`.pyo` are skipped, matching `_code_dir_core_tree`'s own
    exclusion."""
    import shutil
    dest = repo / "core"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        _FW_ROOT / "core", dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    subprocess.run(["git", "add", "-A", "core"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "mirror _FW_ROOT core/ for the widened commit check"],
                   cwd=repo, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_record_run_wraps_rows_with_measured_index_generation_and_command(tmp_path):
    """AC-14/AC-12: `record_run` wraps the backfill's own rows with `label`,
    `code_commit`, a portable `command`, `measured` and `index_generation`.
    The stand-in `.klc/` stays byte-identical. `code_commit` here is
    deliberately a commit in `fx["repo"]` whose WHOLE `core/` tree really is
    a byte-exact copy of `_FW_ROOT`'s own `core/` (external review F-1/F-3's
    accepted case — a matching commit is still accepted after the
    whole-subtree check is added, step-7)."""
    from core.skills import baseline_compare as bc

    fx = _write_hermetic_corpus(tmp_path)
    before_tickets = _hash_tree(fx["tickets_root"])
    before_index = _hash_tree(fx["index_dir"])
    work = tmp_path / "work"
    out = tmp_path / "rec" / "corrected.json"
    code_commit = _mirror_fw_core_commit(fx["repo"])

    backfill_args = ["--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
                     "--index", str(fx["index_dir"]), "--repo", str(fx["repo"])]
    record = bc.record_run("corrected", _FW_ROOT, code_commit, backfill_args, work, out)

    assert record["label"] == "corrected"
    assert record["code_commit"] == code_commit
    assert record["command"].startswith("python3 CODE_DIR/core/skills/planning-eval.py --backfill")
    assert str(_FW_ROOT) not in record["command"]
    assert str(work) not in record["command"]
    assert str(fx["repo"]) not in record["command"]
    assert sys.executable not in record["command"]
    assert record["index_generation"] == "gen-1"

    out_md_text = (work / "corrected.md").read_text(encoding="utf-8")
    measured_line = next(ln for ln in out_md_text.splitlines() if ln.startswith("- measured:"))
    assert record["measured"] == measured_line.split(":", 1)[1].strip()

    out_json = json.loads((work / "corrected.json").read_text(encoding="utf-8"))
    assert record["rows"] == out_json["rows"]

    assert _hash_tree(fx["tickets_root"]) == before_tickets
    assert _hash_tree(fx["index_dir"]) == before_index
    assert json.loads(out.read_text(encoding="utf-8")) == record


def test_record_refuses_old_label_on_a_tree_without_the_all_probe(tmp_path):
    """D-2 negative: label `old` with `_FW_ROOT` (fixed code, no `--all`
    probe left in `git_touched`) raises `RecordError`, and `out` does not
    exist."""
    from core.skills import baseline_compare as bc

    fx = _write_hermetic_corpus(tmp_path)
    backfill_args = ["--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
                     "--index", str(fx["index_dir"]), "--repo", str(fx["repo"])]
    out = tmp_path / "rec" / "old.json"
    try:
        bc.record_run("old", _FW_ROOT, "abc1234", backfill_args, tmp_path / "work", out)
        assert False, "expected RecordError"
    except bc.RecordError:
        pass
    assert not out.exists()


def test_record_refuses_corrected_label_on_a_tree_with_the_all_probe(tmp_path):
    """D-2 negative twin: a stub code tree whose `core/skills/planning-eval.py`
    has a `git_touched` holding the constant `--all` is refused for
    `corrected`."""
    from core.skills import baseline_compare as bc

    stub = tmp_path / "stub-code"
    (stub / "core" / "skills").mkdir(parents=True)
    (stub / "core" / "skills" / "planning-eval.py").write_text(
        "def git_touched(key, repo):\n"
        "    return _git(['log', '--all', '-E', '--grep=x'], repo)\n"
    )
    fx = _write_hermetic_corpus(tmp_path)
    backfill_args = ["--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
                     "--index", str(fx["index_dir"]), "--repo", str(fx["repo"])]
    out = tmp_path / "rec" / "corrected.json"
    try:
        bc.record_run("corrected", stub, "abc1234", backfill_args, tmp_path / "work", out)
        assert False, "expected RecordError"
    except bc.RecordError:
        pass
    assert not out.exists()


def test_record_fails_closed_when_the_backfill_exits_non_zero(tmp_path):
    """Fail closed: a stub `old` tree (it holds `--all`) whose script exits 1
    makes `record_run` raise `RecordError`; the CLI form returns exit 2, and
    `out` does not exist. `code_commit` is deliberately a real, matching
    commit of the STUB's own bytes so this exercises the intended
    'backfill exits non-zero' path, not external review F-1's new commit
    check (that has its own, separate tests below)."""
    from core.skills import baseline_compare as bc

    stub = tmp_path / "stub-code"
    (stub / "core" / "skills").mkdir(parents=True)
    (stub / "core" / "skills" / "planning-eval.py").write_text(
        "def git_touched(key, repo):\n"
        "    _all_probe = '--all'  # the constant the AST scan must find\n"
        "    return ([], False)\n"
        "import sys\n"
        "sys.exit(1)\n"
    )
    fx = _write_hermetic_corpus(tmp_path)
    code_commit = _record_code_commit(
        fx["repo"], (stub / "core" / "skills" / "planning-eval.py").read_bytes())
    backfill_args = ["--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
                     "--index", str(fx["index_dir"]), "--repo", str(fx["repo"])]
    out = tmp_path / "rec" / "old.json"
    try:
        bc.record_run("old", stub, code_commit, backfill_args, tmp_path / "work", out)
        assert False, "expected RecordError"
    except bc.RecordError:
        pass
    assert not out.exists()

    argv = ["record", "--label", "old", "--code-dir", str(stub), "--code-commit", code_commit,
           "--work-dir", str(tmp_path / "work2"), "--out", str(out), "--"] + backfill_args
    rc = bc.main(argv)
    assert rc == 2
    assert not out.exists()


def test_record_refuses_mismatched_code_commit(tmp_path):
    """external review F-1: a `--code-commit` that resolves fine in `--repo`
    but whose `core/skills/planning-eval.py` blob at that commit differs
    from `--code-dir`'s own file is refused — the operator-typed commit is
    machine-checked against the tree, never taken on faith."""
    from core.skills import baseline_compare as bc

    fx = _write_hermetic_corpus(tmp_path)
    wrong_commit = _record_code_commit(
        fx["repo"], b"def git_touched(key, repo):\n    return ([], False)\n")
    backfill_args = ["--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
                     "--index", str(fx["index_dir"]), "--repo", str(fx["repo"])]
    out = tmp_path / "rec" / "corrected.json"
    try:
        bc.record_run("corrected", _FW_ROOT, wrong_commit, backfill_args,
                      tmp_path / "work", out)
        assert False, "expected RecordError"
    except bc.RecordError:
        pass
    assert not out.exists()


def test_record_refuses_unresolvable_code_commit(tmp_path):
    """external review F-1 twin: a `--code-commit` that does not resolve at
    all in `--repo` (no such object, or no such path at that commit) is
    refused the same way, never treated as 'unverifiable, proceed anyway'."""
    from core.skills import baseline_compare as bc

    fx = _write_hermetic_corpus(tmp_path)
    backfill_args = ["--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
                     "--index", str(fx["index_dir"]), "--repo", str(fx["repo"])]
    out = tmp_path / "rec" / "corrected.json"
    try:
        bc.record_run("corrected", _FW_ROOT, "deadbeefcafef00dfeedfacecafebeefdeadbeef",
                      backfill_args, tmp_path / "work", out)
        assert False, "expected RecordError"
    except bc.RecordError:
        pass
    assert not out.exists()


# --------------------------------------------------------------------------- #
# step-7 — review round 2 external F-3: --repo parsing, missing-file
# RecordErrors, separate resolve/blob-diff messages, whole-core/ widening
# --------------------------------------------------------------------------- #
def test_repo_from_backfill_args_parses_space_and_equals_forms():
    """external review F-3: `--repo PATH` and `--repo=PATH` are both
    recognised (the old code only matched the separate-token form, so
    `--repo=PATH` silently behaved like no `--repo` at all)."""
    from core.skills import baseline_compare as bc

    assert bc._repo_from_backfill_args(
        ["--tickets", "T", "--repo", "/a/b"]) == Path("/a/b")
    assert bc._repo_from_backfill_args(
        ["--tickets", "T", "--repo=/a/b"]) == Path("/a/b")
    assert bc._repo_from_backfill_args(["--tickets", "T"]) is None


def test_repo_from_backfill_args_trailing_bare_repo_raises_record_error():
    """external review F-3: a trailing `--repo` with no value after it
    raises `RecordError` (exit 2 at the CLI), never an `IndexError`."""
    from core.skills import baseline_compare as bc

    try:
        bc._repo_from_backfill_args(["--tickets", "T", "--repo"])
        assert False, "expected RecordError"
    except bc.RecordError:
        pass


def test_portable_substitutes_repo_root_for_the_equals_form(tmp_path):
    """external review F-3: `_portable`'s `REPO_ROOT` substitution also
    fires when `--repo` was given as `--repo=PATH` (previously
    `_repo_from_backfill_args` returned `None` for that form, so the
    substitution silently never happened and the raw path leaked into the
    portable command)."""
    from core.skills import baseline_compare as bc

    code_dir = tmp_path / "code"
    work_dir = tmp_path / "work"
    repo_dir = tmp_path / "repo"
    argv = ["python3", "script.py", f"--repo={repo_dir}"]
    command = bc._portable(argv, code_dir, work_dir, [f"--repo={repo_dir}"])
    assert str(repo_dir) not in command
    assert "REPO_ROOT" in command


def test_record_refuses_code_dir_missing_planning_eval(tmp_path):
    """external review F-3: a `--code-dir` with no
    `core/skills/planning-eval.py` at all raises `RecordError`, not a bare
    `FileNotFoundError` escaping from the label check."""
    from core.skills import baseline_compare as bc

    empty_code_dir = tmp_path / "empty-code"
    empty_code_dir.mkdir()
    fx = _write_hermetic_corpus(tmp_path)
    backfill_args = ["--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
                     "--index", str(fx["index_dir"]), "--repo", str(fx["repo"])]
    out = tmp_path / "rec" / "old.json"
    try:
        bc.record_run("old", empty_code_dir, "abc1234", backfill_args, tmp_path / "work", out)
        assert False, "expected RecordError"
    except bc.RecordError:
        pass
    except FileNotFoundError:
        assert False, "FileNotFoundError must not escape record_run (external review F-3)"
    assert not out.exists()


def test_code_commit_mismatch_messages_distinguish_resolve_from_blob_diff(tmp_path):
    """external review F-3: the refusal message for an UNRESOLVABLE
    `--code-commit` reads differently from the one for a commit that
    resolves fine but disagrees blob for blob — the latter names BOTH blob
    ids."""
    from core.skills import baseline_compare as bc

    fx = _write_hermetic_corpus(tmp_path)
    backfill_args = ["--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
                     "--index", str(fx["index_dir"]), "--repo", str(fx["repo"])]

    out = tmp_path / "rec" / "unresolvable.json"
    unresolvable_message = None
    try:
        bc.record_run("corrected", _FW_ROOT, "deadbeefcafef00dfeedfacecafebeefdeadbeef",
                      backfill_args, tmp_path / "work1", out)
        assert False, "expected RecordError"
    except bc.RecordError as exc:
        unresolvable_message = str(exc)
    assert "does not resolve" in unresolvable_message

    wrong_commit = _record_code_commit(
        fx["repo"], b"def git_touched(key, repo):\n    return ([], False)\n")
    out2 = tmp_path / "rec" / "mismatch.json"
    mismatch_message = None
    try:
        bc.record_run("corrected", _FW_ROOT, wrong_commit, backfill_args,
                      tmp_path / "work2", out2)
        assert False, "expected RecordError"
    except bc.RecordError as exc:
        mismatch_message = str(exc)

    assert mismatch_message != unresolvable_message
    assert "does not resolve" not in mismatch_message
    assert "blob" in mismatch_message
    local_blob = bc.git_blob_id(_SKILL.read_bytes())
    remote_blob = bc.git_blob_id(b"def git_touched(key, repo):\n    return ([], False)\n")
    assert local_blob in mismatch_message
    assert remote_blob in mismatch_message


def test_record_widened_check_catches_file_present_only_on_one_side(tmp_path):
    """external review F-3: the code-commit check now compares the WHOLE
    `core/` subtree, not just `core/skills/planning-eval.py` — a file that
    exists on only one side is reported as a mismatch even when every file
    both sides DO share is byte-identical."""
    from core.skills import baseline_compare as bc

    code_dir = tmp_path / "code"
    (code_dir / "core" / "skills").mkdir(parents=True)
    (code_dir / "core" / "skills" / "planning-eval.py").write_bytes(_SKILL.read_bytes())
    (code_dir / "core" / "skills" / "extra_only_in_code_dir.py").write_text("x = 1\n")

    fx = _write_hermetic_corpus(tmp_path)
    code_commit = _record_code_commit(fx["repo"], _SKILL.read_bytes())
    backfill_args = ["--tickets", str(fx["tickets_root"]), "--modules", str(fx["modules"]),
                     "--index", str(fx["index_dir"]), "--repo", str(fx["repo"])]
    out = tmp_path / "rec" / "corrected.json"
    try:
        bc.record_run("corrected", code_dir, code_commit, backfill_args,
                      tmp_path / "work", out)
        assert False, "expected RecordError"
    except bc.RecordError as exc:
        message = str(exc)
        assert "extra_only_in_code_dir.py" in message
        assert "present in" in message
    assert not out.exists()


# --------------------------------------------------------------------------- #
# step-5 — the re-published doc, rendered from three committed inputs
# --------------------------------------------------------------------------- #
def _md_section(text: str, heading: str) -> str:
    """The text from *heading* (inclusive) up to the next `\n## ` heading, or
    to the end of *text* if there is none."""
    start = text.index(heading)
    rest = text[start:]
    nxt = rest.find("\n## ", len(heading))
    return rest if nxt == -1 else rest[:nxt]


def test_doc_has_three_column_summary_table_per_population():
    """AC-8: inside the generated block, `### stored` and `### replayed`
    each carry the three-column header and five metric rows with three
    non-empty value cells."""
    import re
    from core.skills import baseline_compare as bc

    doc_text = _BASELINE_DOC.read_text(encoding="utf-8")
    start = doc_text.index(bc.BEGIN_MARK)
    end = doc_text.index(bc.END_MARK) + len(bc.END_MARK)
    block = doc_text[start:end]
    header = ("| metric | published 2026-09-25 | old ground truth, today | "
             "corrected ground truth, today |")
    for source in ("stored", "replayed"):
        assert f"### {source}" in block
        section = block.split(f"### {source}", 1)[1]
        nxt = section.find("\n### ")
        section = section if nxt == -1 else section[:nxt]
        assert header in section
        for label in ("tickets total", "tickets scored", "tickets unavailable",
                     "precision@5 mean", "recall@10 mean"):
            m = re.search(
                rf"^\| {re.escape(label)} \| (\S.*?) \| (\S.*?) \| (\S.*?) \|$",
                section, re.MULTILINE)
            assert m, f"missing three-column row for {label!r} in {source!r}"
            assert all(g.strip() for g in m.groups()), (
                f"empty value cell for {label!r} in {source!r}")


def test_rerender_from_three_committed_inputs_matches_doc_byte_for_byte():
    """AC-9/AC-14: `render_comparison` over the three committed inputs
    equals the doc's `BEGIN_MARK`..`END_MARK` block, byte for byte (the
    header lines — measured times, index generation, corpus count,
    availability per population, both commands, code commits — live
    inside that block)."""
    from core.skills import baseline_compare as bc

    snapshot_text = (_BASELINE_D / "published-1e4a3734.md").read_text(encoding="utf-8")
    old = json.loads((_BASELINE_D / "old.json").read_text(encoding="utf-8"))
    corrected = json.loads((_BASELINE_D / "corrected.json").read_text(encoding="utf-8"))

    rendered = bc.render_comparison(
        snapshot_text, "1e4a3734:docs/20260920_klc110-retrieval-baseline.md",
        old, corrected)

    doc_text = _BASELINE_DOC.read_text(encoding="utf-8")
    start = doc_text.index(bc.BEGIN_MARK)
    end = doc_text.index(bc.END_MARK) + len(bc.END_MARK)
    assert doc_text[start:end] == rendered.rstrip("\n")


def test_rerender_is_deterministic_given_same_three_inputs():
    """AC-9: two renders of the committed inputs are byte-identical."""
    from core.skills import baseline_compare as bc

    snapshot_text = (_BASELINE_D / "published-1e4a3734.md").read_text(encoding="utf-8")
    old = json.loads((_BASELINE_D / "old.json").read_text(encoding="utf-8"))
    corrected = json.loads((_BASELINE_D / "corrected.json").read_text(encoding="utf-8"))

    r1 = bc.render_comparison(
        snapshot_text, "1e4a3734:docs/20260920_klc110-retrieval-baseline.md",
        old, corrected)
    r2 = bc.render_comparison(
        snapshot_text, "1e4a3734:docs/20260920_klc110-retrieval-baseline.md",
        old, corrected)
    assert r1 == r2


def test_reference_points_verbatim_plus_one_dated_annotation_block():
    """AC-11: the `## The reference points` section of the doc equals the
    snapshot's section plus exactly one trailing block matching
    `^> \\*\\*Annotation, \\d{4}-\\d{2}-\\d{2} \\(KLC-149\\)\\.\\*\\*`, and
    that block names `0.2414`, `0.1964`, `115` and `0.2487`."""
    import re

    doc_text = _BASELINE_DOC.read_text(encoding="utf-8")
    snapshot_text = (_BASELINE_D / "published-1e4a3734.md").read_text(encoding="utf-8")

    doc_section = _md_section(doc_text, "## The reference points")
    snap_section = _md_section(snapshot_text, "## The reference points")

    assert doc_section.startswith(snap_section), (
        "the reference-points section was changed, not just extended")
    tail = doc_section[len(snap_section):]

    matches = re.findall(
        r"^> \*\*Annotation, \d{4}-\d{2}-\d{2} \(KLC-149\)\.\*\*", tail, re.MULTILINE)
    assert len(matches) == 1, f"expected exactly one annotation block, found {len(matches)}"
    for needle in ("0.2414", "0.1964", "115", "0.2487"):
        assert needle in tail, f"annotation block is missing {needle!r}"


def test_published_snapshot_is_the_1e4a3734_blob():
    """AC-9/D-204: `git_blob_id` of the committed snapshot bytes equals the
    1e4a3734 blob object id — the published column is pinned to the exact
    historical blob, not to a working-tree copy. external review F-5: the
    literal was evidenced only by `git hash-object` of the same committed
    copy, which pins the copy to itself, not to history. When the tree this
    test runs in still carries that commit (the live repo — a history-less
    `git archive` scratch copy does not), the SAME id is cross-checked
    against `git rev-parse 1e4a3734:<doc>` run directly against that
    history, so the literal is pinned to an independent source too."""
    from core.skills import baseline_compare as bc

    snapshot_bytes = (_BASELINE_D / "published-1e4a3734.md").read_bytes()
    assert bc.git_blob_id(snapshot_bytes) == "aa5f1965899792409df9b3e1888002d77fc9dbea"

    probe = subprocess.run(
        ["git", "rev-parse", "1e4a3734:docs/20260920_klc110-retrieval-baseline.md"],
        capture_output=True, text=True, cwd=str(_FW_ROOT))
    if probe.returncode == 0:
        assert probe.stdout.strip() == "aa5f1965899792409df9b3e1888002d77fc9dbea"


def test_committed_runs_share_index_generation_and_corpus():
    """AC-9/A-001: `old.json` has label `old`, `corrected.json` has label
    `corrected`, both share `index_generation` and the same
    `(ticket, trace_source)` set, and they have different `code_commit`s."""
    old = json.loads((_BASELINE_D / "old.json").read_text(encoding="utf-8"))
    corrected = json.loads((_BASELINE_D / "corrected.json").read_text(encoding="utf-8"))

    assert old["label"] == "old"
    assert corrected["label"] == "corrected"
    assert old["index_generation"] == corrected["index_generation"]

    def _keys(run: dict) -> set:
        return {(r["ticket"], r["trace_source"])
               for rows in run["rows"].values() for r in rows}

    assert _keys(old) == _keys(corrected)
    assert old["code_commit"] != corrected["code_commit"]


# --------------------------------------------------------------------------- #
# step-8 — review round 3 external F-3: `_repo_core_tree`/`_code_dir_core_tree`
# path-quoting and symlink edge cases
# --------------------------------------------------------------------------- #
def test_repo_core_tree_matches_code_dir_tree_for_non_ascii_filename(tmp_path):
    """review round 3 external F-3: `git ls-tree` C-quotes a non-ASCII path
    into octal escapes by default (`core.quotePath`), so the OLD
    `_repo_core_tree` (`git ls-tree -r <commit> -- core/`, no `-z`, split on
    `\\n`) never matched a non-ASCII `core/` filename against
    `_code_dir_core_tree`'s raw, un-quoted `Path.relative_to(...).as_posix()`
    string — a real, byte-identical file would be reported as present on
    only ONE side, on BOTH sides at once. `-z` turns path quoting off
    entirely, so the two trees now agree."""
    from core.skills import baseline_compare as bc

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True,
                   capture_output=True)
    name = "café.py"
    skills_dir = repo / "core" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / name).write_bytes(b"x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "non-ascii filename"], cwd=repo, check=True,
                   capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                            capture_output=True, text=True).stdout.strip()

    code_dir = tmp_path / "code"
    (code_dir / "core" / "skills").mkdir(parents=True)
    (code_dir / "core" / "skills" / name).write_bytes(b"x = 1\n")

    repo_tree = bc._repo_core_tree(repo, commit)
    code_tree = bc._code_dir_core_tree(code_dir)
    assert repo_tree is not None
    assert f"core/skills/{name}" in repo_tree
    assert repo_tree == code_tree


def test_code_dir_core_tree_refuses_symlink_under_core(tmp_path):
    """review round 3 external F-3: a symlink under `--code-dir`'s `core/`
    must be REFUSED, not silently followed — `Path.is_file()` follows a
    symlink through to its target, so the old code would hash whatever the
    link resolves to, a file that may live outside `core/` entirely, may
    not exist at the compared commit at all, or may rot after the record is
    made. `_code_dir_core_tree` now raises `RecordError` naming the
    symlink's own path instead."""
    import os
    from core.skills import baseline_compare as bc

    code_dir = tmp_path / "code"
    skills_dir = code_dir / "core" / "skills"
    skills_dir.mkdir(parents=True)
    real = tmp_path / "outside.py"
    real.write_text("x = 1\n")
    link = skills_dir / "linked.py"
    os.symlink(real, link)

    try:
        bc._code_dir_core_tree(code_dir)
        assert False, "expected RecordError"
    except bc.RecordError as exc:
        assert "linked.py" in str(exc)
