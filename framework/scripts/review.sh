#!/usr/bin/env bash
# review.sh — drive the multi-agent code review.
#
# Usage:
#   ./framework/scripts/review.sh --diff <path|git-ref> --spec <path> [--external]
#
# The script:
#   1. Resolves --diff to a unified-diff file (git ref or already-a-file).
#   2. Collects CLAUDE.md context for modules whose files appear in the diff.
#   3. Launches 5 internal review sub-agents in parallel (background jobs).
#   4. Waits for all partials, parses ISSUES_TOTAL / ISSUES_BLOCKING trailers.
#   5. Optionally runs the external-review agent (--external or config flag).
#   6. Renders the final report from framework/core/templates/review-report.md.j2
#      via a small python helper embedded below.
#   7. Prints the report path, prints the verdict, exits 0 (APPROVED) or
#      1 (CHANGES REQUESTED) for CI integration.
#
# The script does NOT invoke LLMs directly. Where a sub-agent prompt needs
# an LLM, the script writes a job card to framework/reports/pending/ that
# lists the prompt file + context bundle, and then waits for partial reports
# to appear in framework/reports/. This keeps the script usable both from
# Claude Code (which fulfils the job cards) and from CI (where an operator
# or a wrapper is expected to execute the prompts).
#
# All text is English.

set -uo pipefail

FRAMEWORK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$FRAMEWORK_ROOT/.." && pwd)"
cd "$PROJECT_ROOT"

die()  { echo "[review][err] $*" >&2; exit 2; }
log()  { echo "[review] $*"; }

DIFF_ARG=""
SPEC_ARG=""
EXTERNAL=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --diff)     DIFF_ARG="$2"; shift 2 ;;
    --spec)     SPEC_ARG="$2"; shift 2 ;;
    --external) EXTERNAL=1;    shift ;;
    -h|--help)
      sed -n '3,25p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$DIFF_ARG" ] || die "missing --diff"
[ -n "$SPEC_ARG" ] || die "missing --spec (path to spec or bug description)"
[ -f "$SPEC_ARG" ] || die "spec file not found: $SPEC_ARG"

TS="$(date -u +%Y-%m-%d-%H-%M)"
REPORTS_DIR="$FRAMEWORK_ROOT/reports"
PENDING_DIR="$REPORTS_DIR/pending-$TS"
PARTIALS_DIR="$REPORTS_DIR/partials-$TS"
mkdir -p "$REPORTS_DIR" "$PENDING_DIR" "$PARTIALS_DIR"

# ---- 0. Retention: prune stale pending-*/partials-* + oldest review-*.md ----
# Defaults match framework/config/reviewers.yml (retention_partials_days=7,
# retention_runs=30). Configurable overrides are optional; defaults are sane.
RETENTION_PARTIALS_DAYS="${RETENTION_PARTIALS_DAYS:-7}"
RETENTION_RUNS="${RETENTION_RUNS:-30}"
find "$REPORTS_DIR" -maxdepth 1 -type d \
  \( -name 'pending-*' -o -name 'partials-*' \) \
  -mtime +"$RETENTION_PARTIALS_DAYS" -print0 2>/dev/null \
  | xargs -0 -r rm -rf
# Keep the N most recent review-*.md files; delete older ones. We use
# python (always available thanks to our other skills) so filenames with
# spaces / unicode / newlines are handled safely.
python3 - "$REPORTS_DIR" "$RETENTION_RUNS" <<'PY'
import os, sys
from pathlib import Path
reports_dir = Path(sys.argv[1])
keep = int(sys.argv[2])
files = sorted(reports_dir.glob("review-*.md"),
               key=lambda p: p.stat().st_mtime, reverse=True)
for old in files[keep:]:
    try: old.unlink()
    except OSError: pass
PY

# ---- 1. Resolve --diff ------------------------------------------------------
DIFF_FILE="$PENDING_DIR/diff.patch"
if [ -f "$DIFF_ARG" ]; then
  cp "$DIFF_ARG" "$DIFF_FILE"
else
  if ! git -C "$PROJECT_ROOT" rev-parse --verify "$DIFF_ARG" >/dev/null 2>&1; then
    die "--diff is neither a file nor a resolvable git ref: $DIFF_ARG"
  fi
  git -C "$PROJECT_ROOT" diff "$DIFF_ARG" > "$DIFF_FILE" \
    || die "git diff against '$DIFF_ARG' failed"
fi
log "Diff: $DIFF_FILE ($(wc -l < "$DIFF_FILE" | tr -d ' ') lines)"

# Improvement 1: record the diff's content hash so partial-reuse can verify
# that stale partials from a different diff are never trusted.
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$DIFF_FILE" | awk '{print $1}' > "$PARTIALS_DIR/diff.sha256"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$DIFF_FILE" | awk '{print $1}' > "$PARTIALS_DIR/diff.sha256"
fi
CURRENT_DIFF_HASH="$(cat "$PARTIALS_DIR/diff.sha256" 2>/dev/null || true)"

# Stamp the active profile next to the hash. Reusing partials from a run
# that used a different profile would silently mix reviewer sets; the
# check below guards against that.
CURRENT_PROFILE="$(python3 framework/core/skills/profile-resolve.py --field name 2>/dev/null || echo unknown)"
echo "$CURRENT_PROFILE" > "$PARTIALS_DIR/profile.txt"

# ---- 2. CLAUDE.md context ---------------------------------------------------
CTX_FILE="$PENDING_DIR/claude-md-context.md"
: > "$CTX_FILE"
[ -f "$PROJECT_ROOT/CLAUDE.md" ] && {
  echo "<!-- BEGIN root CLAUDE.md -->" >> "$CTX_FILE"
  cat "$PROJECT_ROOT/CLAUDE.md"        >> "$CTX_FILE"
  echo "<!-- END root CLAUDE.md -->"   >> "$CTX_FILE"
}

# Resolve affected modules strictly via longest-prefix match on each
# file in the diff. This avoids the `grep -F` substring trap where
# (e.g.) `CrushDemo/Source/CrushDemo/` would match any file under
# `CrushDemo/Source/CrushDemoTests/`. The skill parses `+++ b/<path>`
# and walks modules sorted by descending path length.
MODS_JSON="$FRAMEWORK_ROOT/index/modules.json"
AFFECTED_MODS="$PENDING_DIR/affected-modules.txt"
: > "$AFFECTED_MODS"
if [ -f "$MODS_JSON" ]; then
  python3 framework/core/skills/diff-modules.py "$DIFF_FILE" --modules "$MODS_JSON" \
    > "$AFFECTED_MODS" 2>/dev/null || true
fi

if [ -s "$AFFECTED_MODS" ] && command -v jq >/dev/null 2>&1; then
  declare -A __MODPATH=() __MODDOC=()
  while IFS=$'\t' read -r NAME MPATH DOC_FILENAME; do
    [ -z "$NAME" ] && continue
    __MODPATH[$NAME]="$MPATH"
    __MODDOC[$NAME]="${DOC_FILENAME:-CLAUDE.md}"
  done < <(jq -r '.modules[] | [.name, .path, (.doc_filename // "")] | @tsv' "$MODS_JSON")

  while read -r NAME; do
    [ -z "$NAME" ] && continue
    MPATH="${__MODPATH[$NAME]:-}"
    DOC_FILENAME="${__MODDOC[$NAME]:-CLAUDE.md}"
    [ -z "$MPATH" ] && continue
    DOC="$PROJECT_ROOT/$MPATH/$DOC_FILENAME"
    if [ -f "$DOC" ]; then
      {
        echo "<!-- BEGIN module $NAME ($MPATH) -->"
        cat "$DOC"
        echo "<!-- END module $NAME -->"
      } >> "$CTX_FILE"
    fi
  done < "$AFFECTED_MODS"
fi
log "Context bundle: $CTX_FILE"

# ---- 3. Emit job cards for the internal sub-agents --------------------------
# Reviewer list + conditional triggers come from the active profile's
# manifest. A reviewer's short name is the prompt file's basename without
# extension (e.g. core/agents/review/security.md -> "security").
REVIEWERS_JSON="$(python3 framework/core/skills/profile-resolve.py --field reviewers)"

# Flatten into arrays: name -> prompt path + optional filter regex.
# Tabs separate fields; empty fields are legal (no filter = full diff).
declare -a REVIEWERS=()
declare -A REVIEWER_PROMPT=()
declare -A REVIEWER_FILTER=()
while IFS=$'\t' read -r name path filter; do
  [ -z "$name" ] && continue
  REVIEWERS+=("$name")
  REVIEWER_PROMPT[$name]="$path"
  REVIEWER_FILTER[$name]="$filter"
done < <(echo "$REVIEWERS_JSON" | python3 -c '
import json, os, sys
d = json.load(sys.stdin)
for r in d.get("always", []):
    p = r["path"]; f = r.get("filter","") or ""
    print(os.path.splitext(os.path.basename(p))[0] + "\t" + p + "\t" + f)
')

# Conditional reviewers: include only if the diff matches the trigger.
while IFS=$'\t' read -r name path trigger filter; do
  [ -z "$name" ] && continue
  # Validate the trigger regex first. grep exit codes: 0=match, 1=no match,
  # 2+=invocation error (bad regex, missing file). Without this split a
  # broken regex in manifest would masquerade as "no match" and silently
  # drop the reviewer.
  echo "" | grep -qE "$trigger" 2>/dev/null; rc=$?
  if [ "$rc" -ge 2 ]; then
    die "reviewer '$name': bad trigger regex in profile manifest: $trigger"
  fi
  if grep -qE "$trigger" "$DIFF_FILE" 2>/dev/null; then
    REVIEWERS+=("$name")
    REVIEWER_PROMPT[$name]="$path"
    REVIEWER_FILTER[$name]="$filter"
  else
    # Skip partial: no [SEVERITY] heading — the aggregator counts issues
    # from `### [SEVERITY]` lines only, so a skip partial must not contain
    # one. The aggregator will still pick the reviewer up in its summary
    # table with zero issues; reviewer_label() formats the display name.
    cat > "$PARTIALS_DIR/$name.partial.md" <<EOF_SKIP
## $name Review

_reviewer skipped (conditional trigger not matched)_

ISSUES_TOTAL=0 ISSUES_BLOCKING=0
EOF_SKIP
  fi
done < <(echo "$REVIEWERS_JSON" | python3 -c '
import json, os, sys
d = json.load(sys.stdin)
for r in d.get("conditional", []):
    p = r["path"]; t = r.get("trigger", ""); f = r.get("filter","") or ""
    print(os.path.splitext(os.path.basename(p))[0] + "\t" + p + "\t" + t + "\t" + f)
')

for r in "${REVIEWERS[@]}"; do
  card="$PENDING_DIR/job-$r.md"
  partial="$PARTIALS_DIR/$r.partial.md"
  prompt="framework/${REVIEWER_PROMPT[$r]}"
  # Per-reviewer diff: if the profile manifest declared a `filter` regex
  # for this reviewer, produce a trimmed diff containing only files that
  # match. Otherwise the reviewer sees the full diff (security, etc.).
  filter="${REVIEWER_FILTER[$r]}"
  if [ -n "$filter" ]; then
    reviewer_diff="$PENDING_DIR/diff-$r.patch"
    python3 framework/core/skills/filter-diff.py \
      "$DIFF_FILE" "$filter" "$reviewer_diff" \
      || { reviewer_diff="$DIFF_FILE"; log "filter-diff failed for $r; using full diff"; }
  else
    reviewer_diff="$DIFF_FILE"
  fi

  # Per-reviewer CTX: rebuild the claude_md bundle from only the modules
  # touched by this reviewer's diff. A reviewer reading a subset of the
  # diff doesn't need every module's CLAUDE.md. If no filter or no
  # modules.json, fall back to the full context file.
  reviewer_ctx="$CTX_FILE"
  if [ -n "$filter" ] && [ -f "$MODS_JSON" ]; then
    reviewer_ctx="$PENDING_DIR/ctx-$r.md"
    : > "$reviewer_ctx"
    # Include only the <!-- BEGIN: head --> ... <!-- END: head --> slice
    # of the root CLAUDE.md — conventions and languages are relevant to
    # every reviewer, the module table is not (we already picked the
    # relevant modules below).
    ROOT_MD="$PROJECT_ROOT/CLAUDE.md"
    if [ -f "$ROOT_MD" ]; then
      python3 - "$ROOT_MD" >> "$reviewer_ctx" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"<!--\s*BEGIN:\s*head\s*-->(.*?)<!--\s*END:\s*head\s*-->", text, re.DOTALL)
# If the template lacks head markers (older CLAUDE.md), fall back to the
# full file — not our job to refuse.
print(m.group(1).strip() if m else text)
PY
    fi
    # Affected modules for this reviewer's trimmed diff only.
    reviewer_mods=$(python3 framework/core/skills/diff-modules.py \
                      "$reviewer_diff" --modules "$MODS_JSON" 2>/dev/null || true)
    if [ -n "$reviewer_mods" ]; then
      while read -r RNAME; do
        [ -z "$RNAME" ] && continue
        RMPATH="${__MODPATH[$RNAME]:-}"
        RDOC="${__MODDOC[$RNAME]:-CLAUDE.md}"
        [ -z "$RMPATH" ] && continue
        F="$PROJECT_ROOT/$RMPATH/$RDOC"
        if [ -f "$F" ]; then
          {
            echo
            echo "<!-- BEGIN module $RNAME ($RMPATH) -->"
            cat "$F"
            echo "<!-- END module $RNAME -->"
          } >> "$reviewer_ctx"
        fi
      done <<< "$reviewer_mods"
    fi
  fi

  allowlist="$FRAMEWORK_ROOT/config/reviewer-allowlist.yml"
  cat > "$card" <<EOF
# Review sub-agent job: $r

Prompt file: $prompt
Inputs:
- diff:              $reviewer_diff
- spec:              $SPEC_ARG
- claude_md_context: $reviewer_ctx
- allowlist:         $allowlist

Before emitting any finding, read the allowlist. If a finding matches
an entry whose \`reviewer\` is "$r" or "*", downgrade to INFO and append
\`(allowlisted: <reason>)\` to the title, per the prompt's Hard rules.

Write the sub-agent's output to: $partial

Required trailer (last line of the partial):
  ISSUES_TOTAL=<n> ISSUES_BLOCKING=<n>
EOF
done
log "Job cards: $PENDING_DIR"

# ---- 4. Parallel dispatch (optional; for headless CI) ----------------------
# When the RUN_LOCAL_SUBAGENTS=1 env var is set and $REVIEW_RUNNER points to a
# callable that fulfils a job card, spawn them in parallel. Otherwise the
# script stops here and asks the caller to fulfil the jobs.
if [ "${RUN_LOCAL_SUBAGENTS:-}" = "1" ] && [ -x "${REVIEW_RUNNER:-}" ]; then
  log "Spawning local sub-agent runner for each job card"
  pids=()
  for r in "${REVIEWERS[@]}"; do
    "$REVIEW_RUNNER" "$PENDING_DIR/job-$r.md" "$PARTIALS_DIR/$r.partial.md" &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
else
  cat <<EOF

--- ACTION REQUIRED ---------------------------------------------------------
Five review sub-agents must now be run. Open Claude Code and, for each card
in $PENDING_DIR, execute the prompt in the referenced file and save the
output to the 'Write the sub-agent's output to' path.

Job cards (one per reviewer):
$(ls "$PENDING_DIR"/job-*.md)

When all five partials exist at $PARTIALS_DIR, re-run:
  $(realpath "$0") --diff "$DIFF_ARG" --spec "$SPEC_ARG"${EXTERNAL:+ --external}

The script will skip job-card emission if the partials are already present.
-----------------------------------------------------------------------------
EOF
fi

# If any partial is missing, stop here (after re-entry, they may already
# exist — in which case we fall through to aggregation).
missing=0
for r in "${REVIEWERS[@]}"; do
  [ -f "$PARTIALS_DIR/$r.partial.md" ] || missing=$((missing+1))
done

# Also accept partials produced by a previous invocation, BUT only if their
# stored diff.sha256 matches the current diff. Without this check we would
# silently return a stale verdict (improvement 1).
if [ "$missing" -gt 0 ]; then
  for dir in "$REPORTS_DIR"/partials-*/; do
    ok=1
    for r in "${REVIEWERS[@]}"; do
      [ -f "$dir/$r.partial.md" ] || { ok=0; break; }
    done
    [ "$ok" = "1" ] || continue
    # Compare hashes. Missing hash file => older format, reject as unsafe.
    stored_hash=""
    [ -f "$dir/diff.sha256" ] && stored_hash="$(cat "$dir/diff.sha256")"
    if [ -n "$CURRENT_DIFF_HASH" ] && [ "$stored_hash" != "$CURRENT_DIFF_HASH" ]; then
      log "Skipping ${dir%/} — diff hash mismatch (stale partials)"
      continue
    fi
    # Profile check: refuse reuse when the active profile differs.
    stored_profile=""
    [ -f "$dir/profile.txt" ] && stored_profile="$(cat "$dir/profile.txt")"
    if [ -n "$CURRENT_PROFILE" ] && [ "$stored_profile" != "$CURRENT_PROFILE" ]; then
      log "Skipping ${dir%/} — profile mismatch (was '$stored_profile', now '$CURRENT_PROFILE')"
      continue
    fi
    PARTIALS_DIR="${dir%/}"
    missing=0
    log "Reusing partials from $PARTIALS_DIR"
    break
  done
fi

if [ "$missing" -gt 0 ]; then
  exit 0
fi

# ---- 5. Optional external review -------------------------------------------
EXT_JSON=""
if [ "$EXTERNAL" = "1" ] || grep -qE '^[[:space:]]*enabled:[[:space:]]*true' \
   "$FRAMEWORK_ROOT/config/reviewers.yml" 2>/dev/null; then
  ext_card="$PENDING_DIR/job-external.md"
  ext_out="$PARTIALS_DIR/external.json"
  cat > "$ext_card" <<EOF
# External review job

Prompt:  framework/core/agents/external-review.md
Inputs:
- diff:              $DIFF_FILE
- spec:              $SPEC_ARG
- claude_md_context: $CTX_FILE

The agent must print a JSON summary as documented in external-review.md and
write the full provider-markdown report to the location configured in
framework/config/reviewers.yml (report_path). Save the JSON summary to:
  $ext_out
EOF
  [ -f "$ext_out" ] && EXT_JSON="$ext_out"
fi

# ---- 6. Aggregate and render -----------------------------------------------
FINAL_REPORT="$REPORTS_DIR/review-$TS.md"

python3 - "$FRAMEWORK_ROOT" "$PARTIALS_DIR" "$FINAL_REPORT" "$SPEC_ARG" "$EXT_JSON" "$DIFF_FILE" <<'PY'
import json, re, sys, time
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError:
    sys.stderr.write("review.sh: jinja2 required (pip install jinja2)\n")
    sys.exit(3)

fw_root, partials_dir, final_path, spec_path, ext_json, diff_path = sys.argv[1:7]
fw_root = Path(fw_root); partials_dir = Path(partials_dir); final_path = Path(final_path)

SEVERITY_RE = re.compile(r'^###\s+\[(?P<sev>[A-Z]+)\]\s+(?P<rest>.+)$')

# Out-of-scope heuristic. Parse the diff once: for every touched file
# build two sets of line numbers — the `+` side (new file) and the `-`
# side (old file). A reviewer's file:line is in-scope if it lands in
# either set, so "reviewer points at an old-file line number that was
# modified by this diff" still counts as in-scope.
def parse_diff_scope(path: str):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    scope: dict[str, dict[str, set[int]]] = {}
    current_file = None
    new_line = None
    old_line = None
    HUNK = re.compile(r'^@@ -(?P<ostart>\d+)(?:,\d+)? \+(?P<nstart>\d+)(?:,\d+)? @@')
    for line in text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            scope.setdefault(current_file, {"new": set(), "old": set()})
            continue
        if line.startswith("--- ") or line.startswith("diff "):
            current_file = None
            continue
        m = HUNK.match(line)
        if m and current_file is not None:
            new_line = int(m.group("nstart"))
            old_line = int(m.group("ostart"))
            continue
        if current_file is None or new_line is None or old_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            scope[current_file]["new"].add(new_line)
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            scope[current_file]["old"].add(old_line)
            old_line += 1
        elif line.startswith(" "):
            new_line += 1
            old_line += 1

    return scope

DIFF_SCOPE = parse_diff_scope(diff_path) if diff_path else {}

FILE_LINE_RE = re.compile(r'([\w./\-]+\.\w+):(\d+)')

def classify_scope(title: str) -> bool | None:
    """Return True if finding looks in-scope, False if out-of-scope,
    None if we cannot tell (no file:line in the title).

    Strict longest-suffix match: among diff paths, pick the one that
    equals `file` or ends with `/<file>` (so `Log.cpp` matches
    `CrushNetworkPrediction/Log.cpp` but not `AnotherLog.cpp`); tie-
    break on the longest diff path. In-scope if the line was touched
    on either the new or the old side of the hunk."""
    m = FILE_LINE_RE.search(title)
    if not m:
        return None
    file, line_s = m.group(1), int(m.group(2))
    candidates = []
    for f in DIFF_SCOPE:
        if f == file or f.endswith("/" + file) or file.endswith("/" + f):
            candidates.append(f)
    if not candidates:
        return False
    best = max(candidates, key=len)
    buckets = DIFF_SCOPE[best]
    return line_s in buckets["new"] or line_s in buckets["old"]

def parse_partial(p: Path):
    if not p.exists():
        return {"total": 0, "blocking": 0, "issues": [], "raw": "", "trailer_mismatch": None, "out_of_scope": 0}
    text = p.read_text(encoding="utf-8")
    issues = []
    for line in text.splitlines():
        mm = SEVERITY_RE.match(line.strip())
        if mm:
            title = mm.group("rest").strip()
            scope = classify_scope(title)
            issues.append({
                "severity": mm.group("sev"),
                "title": title,
                "line": line,
                "suspect_out_of_scope": (scope is False),
            })
    total = len([i for i in issues if i["severity"] != "INFO"])
    blocking = len([i for i in issues if i["severity"] in ("CRITICAL","HIGH")])
    out_of_scope = len([i for i in issues if i["suspect_out_of_scope"]])

    trailer_mismatch = None
    m = re.search(r'ISSUES_TOTAL=(\d+)\s+ISSUES_BLOCKING=(\d+)', text)
    if m:
        t_total = int(m.group(1))
        t_blocking = int(m.group(2))
        if (t_total, t_blocking) != (total, blocking):
            trailer_mismatch = (
                f"manual trailer says TOTAL={t_total} BLOCKING={t_blocking}, "
                f"headers show TOTAL={total} BLOCKING={blocking}"
            )
            sys.stderr.write(f"review.sh: {p.name}: {trailer_mismatch}\n")
    return {"total": total, "blocking": blocking, "issues": issues, "raw": text,
            "trailer_mismatch": trailer_mismatch, "out_of_scope": out_of_scope}

# Reviewers are discovered from whatever partials landed in partials_dir.
# Whoever staged the job cards (review.sh, earlier in this run) wrote one
# partial per active reviewer — including INFO-only skip partials for
# conditional reviewers that didn't trigger. No hardcoded list here.
#
# key   = file stem without ".partial" (e.g. "security", "ue-conventions")
# label = key rewritten for humans: hyphens -> spaces, each word capitalised.
#         Two-letter tokens stay upper-case (UE, AI, API).
def reviewer_label(key: str) -> str:
    return " ".join(
        w.upper() if len(w) <= 2 else w.capitalize()
        for w in key.split("-")
    )

reviewers = {}
for p in sorted(partials_dir.glob("*.partial.md")):
    key = p.name[:-len(".partial.md")]
    reviewers[key] = parse_partial(p)

def is_skip_partial(rev: dict) -> bool:
    """A conditional reviewer whose trigger didn't match gets a partial
    with no `[SEVERITY]` headers and the `reviewer skipped` marker. We
    detect it so the report can call it out as "skipped" instead of
    letting the reader mistake 0/0 for "analysed and found clean"."""
    if rev["total"] != 0 or rev["blocking"] != 0:
        return False
    if rev["issues"]:
        return False
    return "reviewer skipped" in (rev.get("raw") or "")

reviewer_rows = [
    {
        "key":      k,
        "label":    reviewer_label(k),
        "total":    reviewers[k]["total"],
        "blocking": reviewers[k]["blocking"],
        "skipped":  is_skip_partial(reviewers[k]),
    }
    for k in reviewers
]

external = None
if ext_json:
    try:
        external_raw = json.loads(Path(ext_json).read_text(encoding="utf-8"))
        external = {
            "model":    external_raw.get("model", "?"),
            "total":    external_raw.get("total", 0),
            "blocking": external_raw.get("blocking", 0),
            "notes":    external_raw.get("notes", ""),
            "path":     external_raw.get("path", ""),
        }
    except Exception as exc:
        sys.stderr.write(f"review.sh: failed to parse external summary: {exc}\n")

def bucket(issues, blocking):
    out = []
    for i in issues:
        if i.get("suspect_out_of_scope"):
            continue  # separate list below
        is_block = i["severity"] in ("CRITICAL","HIGH")
        if blocking == is_block:
            out.append(f"- [{i['severity']}] {i['title']}")
    return "\n".join(out) if out else "_None._"

def bucket_out_of_scope(issues):
    out = []
    for i in issues:
        if not i.get("suspect_out_of_scope"):
            continue
        if i["severity"] == "INFO":
            continue  # observations aren't issues — don't clutter the section
        out.append(f"- [{i['severity']}] {i['title']}")
    return "\n".join(out) if out else "_None._"

all_issues = [i for r in reviewers.values() for i in r["issues"]]
blocking_issues = bucket(all_issues, True)
non_blocking_issues = bucket(all_issues, False)
out_of_scope_issues = bucket_out_of_scope(all_issues)

# Out-of-scope issues don't block the verdict: they're almost always
# reviewer commentary on untouched code. They still appear in the report
# under their own section so a human can triage them.
in_scope_blocking = sum(
    1 for r in reviewers.values() for i in r["issues"]
    if i["severity"] in ("CRITICAL", "HIGH") and not i.get("suspect_out_of_scope")
)
total_blocking = in_scope_blocking + (external["blocking"] if external else 0)
verdict = "APPROVED" if total_blocking == 0 else "CHANGES REQUESTED"

env = Environment(
    loader=FileSystemLoader(str(fw_root / "core" / "templates")),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
tpl = env.get_template("review-report.md.j2")
out = tpl.render(
    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    spec_path=spec_path,
    reviewers=reviewer_rows,
    external=external,
    blocking_issues=blocking_issues,
    non_blocking_issues=non_blocking_issues,
    out_of_scope_issues=out_of_scope_issues,
    verdict=verdict,
)
final_path.write_text(out, encoding="utf-8")
print(f"REPORT {final_path}")
print(f"VERDICT {verdict}")
sys.exit(0 if verdict == "APPROVED" else 1)
PY
status=$?
exit $status
