#!/usr/bin/env bash
# smoke.sh — end-to-end smoke test for the framework pipeline.
#
# Copies the `tiny-py` fixture into a throw-away scratch directory,
# drops a fresh framework template next to it, switches to the generic
# profile, and runs:
#
#   file-scanner.sh → dep-graph.sh → import-graph.py
#   → (manual inventory.json with minimal structure) → public-api-filter.py
#   → module-writer.py --all
#
# Asserts that every stage produces a readable JSON/file and that the
# final CLAUDE.md exists. On first failure prints the path so a human can
# poke around; otherwise cleans up.
#
# Per-project state lives in .klc/ inside the scratch project root.
#
# Usage:   klc/tests/smoke.sh [--keep]
#   --keep  leave the scratch dir behind for inspection.

set -eu

KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

FW_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURE="$FW_ROOT/tests/fixtures/tiny-py"

if [ ! -d "$FIXTURE" ]; then
  echo "smoke: fixture missing at $FIXTURE" >&2; exit 2
fi

SCRATCH="$(mktemp -d)"
cleanup() { [ "$KEEP" = "1" ] || rm -rf "$SCRATCH"; }
trap cleanup EXIT

cp -a "$FIXTURE/." "$SCRATCH/"
# Layout B: install the live klc repo into the scratch project via
# `klc install`. The shim at .klc/bin/klc will forward every call to
# $FW_ROOT/scripts/klc with PROJECT_ROOT pinned.
"$FW_ROOT/scripts/klc" install "$SCRATCH" >/dev/null
export PROJECT_ROOT="$SCRATCH"
# Heredoc python snippets need the klc repo path; quoted heredocs
# don't expand shell vars, so expose via env.
export KLC_FW="$FW_ROOT"

cd "$SCRATCH"

say() { printf '[smoke] %s\n' "$*"; }
fail() { printf '[smoke] FAIL: %s\n' "$*" >&2; [ "$KEEP" = "1" ] && printf '[smoke] scratch preserved at %s\n' "$SCRATCH" >&2; exit 1; }

say "scratch: $SCRATCH"

say "1/4 file-scanner.sh"
bash $FW_ROOT/core/skills/file-scanner.sh > .klc/index/structural.json
python3 -c "import json; json.load(open('.klc/index/structural.json'))" \
  || fail "structural.json did not parse"

say "2/4 dep-graph.sh"
bash $FW_ROOT/core/skills/dep-graph.sh > .klc/index/depgraph.json
python3 -c "
import json, sys
d = json.load(open('.klc/index/depgraph.json'))
ig = d.get('import_graphs', {}).get('python', {})
if not ig or not ig.get('nodes'):
    print('smoke: no python import graph', file=sys.stderr); sys.exit(1)
" || fail "depgraph.json lacks python import graph"

# We don't run a live inventory agent in smoke; compose the minimum
# inventory.json + modules.json that downstream skills need. The real
# pipeline plugs in the LLM step between dep-graph and decompose.
say "3/4 synthetic inventory + modules"
python3 <<'PY'
import json, pathlib, datetime as _dt

struct = json.loads(pathlib.Path(".klc/index/structural.json").read_text())
dep    = json.loads(pathlib.Path(".klc/index/depgraph.json").read_text())

# Module boundary = source_roots. Assign every .py file underneath as a symbol.
modules = []
symbols = []
for sr in struct.get("source_roots", []):
    path = sr["path"].rstrip("/") + "/"
    items = []
    for py in pathlib.Path(sr["path"]).rglob("*.py"):
        name = py.stem
        if name.startswith("_"):
            continue
        items.append({
            "name":      name,
            "kind":      "file",
            "file":      str(py).replace("\\", "/"),
            "line":      1,
            "signature": "",
        })
    modules.append({
        "name":       sr["module"],
        "path":       path,
        "language":   "python",
        "entry":      None,
        "source":     "smoke",
        "public_api":  [i["name"] for i in items],
        "symbol_count": len(items),
        "depends_on":  [],
        "depended_by": [],
    })
    symbols.extend(items)

inventory = {
    "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "git_sha":      "smoke",
    "root":         struct["root"],
    "profile":      struct["profile"],
    "structural":   struct,
    "depgraph":     dep,
    "source_of_truth": {"python": "regex_fallback"},
    "symbols": {
        "python": {"mode": "detailed", "count": len(symbols), "items": symbols},
    },
    "notes": ["smoke-test synthesized inventory"],
}
pathlib.Path(".klc/index/inventory.json").write_text(json.dumps(inventory, indent=2))
pathlib.Path(".klc/index/modules.json").write_text(json.dumps({
    "generated_at": inventory["generated_at"],
    "git_sha":      "smoke",
    "modules":      modules,
    "cycles":       [],
    "notes":        [],
}, indent=2))
PY

say "4/4 public-api-filter + module-writer --all"
python3 $FW_ROOT/core/skills/public-api-filter.py
python3 $FW_ROOT/core/skills/module-writer.py --all > /dev/null

# per-module-hash.py contract: public-api-filter must have written
# the hash file; diff against the stored baseline returns an empty
# change set immediately after generation.
python3 - <<'PY' || fail "per-module-hash write/diff round-trip failed"
import json, os, pathlib, shutil, subprocess, sys
p = pathlib.Path(".klc/index/per-module-hash.json")
if not p.exists():
    print("per-module-hash.json not materialized", file=sys.stderr); sys.exit(1)

env = os.environ.copy(); env["PROJECT_ROOT"] = os.getcwd()
r = subprocess.run(
    ["python3", os.environ["KLC_FW"] + "/core/skills/per_module_hash.py", "diff"],
    capture_output=True, text=True, env=env,
)
if r.returncode != 0:
    print("diff exit", r.returncode, r.stderr, file=sys.stderr); sys.exit(1)
d = json.loads(r.stdout)
if d["changed"] or d["added"] or d["removed"]:
    print("steady state reports drift:", d, file=sys.stderr); sys.exit(1)

# Perturb one module's public_api and ensure diff flags it.
mods_path = pathlib.Path(".klc/index/modules.json")
mods = json.loads(mods_path.read_text())
if not mods.get("modules"):
    print("no modules to perturb", file=sys.stderr); sys.exit(1)
target = mods["modules"][0]["name"]
mods["modules"][0]["public_api"] = list(mods["modules"][0].get("public_api", [])) + ["__smoke_sentinel__"]
mods_path.write_text(json.dumps(mods, indent=2))
r = subprocess.run(
    ["python3", os.environ["KLC_FW"] + "/core/skills/per_module_hash.py", "diff"],
    capture_output=True, text=True, env=env,
)
d = json.loads(r.stdout)
if target not in d["changed"]:
    print(f"expected {target} in changed; got {d}", file=sys.stderr); sys.exit(1)

# module-writer --only regenerates just the named module.
r = subprocess.run(
    ["python3", os.environ["KLC_FW"] + "/core/skills/module-writer.py",
     "--only", target],
    capture_output=True, text=True, env=env,
)
if r.returncode != 0:
    print("module-writer --only exit", r.returncode, r.stderr, file=sys.stderr); sys.exit(1)
PY

[ -f CLAUDE.md ] || fail "root CLAUDE.md not written"
# Every module must end up with its own CLAUDE.md
python3 - <<'PY' || fail "per-module CLAUDE.md missing"
import json, pathlib, sys
mods = json.loads(pathlib.Path(".klc/index/modules.json").read_text()).get("modules", [])
missing = []
for m in mods:
    doc = pathlib.Path(m["path"]) / (m.get("doc_filename") or "CLAUDE.md")
    if not doc.exists():
        missing.append(str(doc))
if missing:
    print("missing module CLAUDE.md files:", missing, file=sys.stderr); sys.exit(1)
PY

# public-api-filter must materialize the per-module symbol index.
python3 - <<'PY' || fail "symbols_by_module.json missing or malformed"
import json, pathlib, sys
p = pathlib.Path(".klc/index/symbols_by_module.json")
if not p.exists():
    print("symbols_by_module.json not written", file=sys.stderr); sys.exit(1)
payload = json.loads(p.read_text())
idx = payload.get("modules") or {}
mods = json.loads(pathlib.Path(".klc/index/modules.json").read_text()).get("modules", [])
for m in mods:
    if m["name"] not in idx:
        print(f"module {m['name']!r} absent from symbols_by_module.json", file=sys.stderr); sys.exit(1)
PY

# context-loader must work against the materialized index alone (no
# inventory.json fall-back). We remove inventory.json in a copy so any
# accidental dependency on it surfaces immediately.
python3 - <<'PY' || fail "context-loader could not read symbols_by_module.json"
import json, os, pathlib, shutil, subprocess, sys, tempfile
# Keep the materialized file but hide inventory.json to prove we don't
# need it on the happy path.
inv = pathlib.Path(".klc/index/inventory.json")
backup = inv.with_suffix(".bak")
shutil.move(str(inv), str(backup))
try:
    env = os.environ.copy()
    env["PROJECT_ROOT"] = os.getcwd()
    mods = json.loads(pathlib.Path(".klc/index/modules.json").read_text()).get("modules", [])
    if not mods:
        print("no modules to check", file=sys.stderr); sys.exit(1)
    names = ",".join(m["name"] for m in mods[:1])
    r = subprocess.run(
        ["python3", os.environ["KLC_FW"] + "/core/skills/context-loader.py",
         "--modules", names, "--format", "json"],
        capture_output=True, text=True, env=env,
    )
    if r.returncode != 0:
        print("context-loader exit", r.returncode, r.stderr, file=sys.stderr)
        sys.exit(1)
    out = json.loads(r.stdout)
    if out.get("included_modules") is None:
        print("context-loader output missing included_modules", file=sys.stderr)
        sys.exit(1)
finally:
    shutil.move(str(backup), str(inv))
PY

# serena-call skill: track/phase policy + cache round-trip + denylist.
python3 - <<'PY' || fail "serena-call.py end-to-end failed"
import json, os, pathlib, subprocess, sys, time

env = os.environ.copy(); env["PROJECT_ROOT"] = os.getcwd()

def run(*args, expect_ok=True):
    r = subprocess.run(["python3", os.environ["KLC_FW"] + "/core/skills/serena-call.py", *args],
                       capture_output=True, text=True, env=env)
    if expect_ok and r.returncode != 0:
        print("serena-call", args, "exit", r.returncode, r.stderr, file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip(), r.returncode

ticket = "TICK-serena"
tdir = pathlib.Path(".klc/tickets") / ticket
tdir.mkdir(parents=True, exist_ok=True)
(tdir / "meta.json").write_text(json.dumps({
    "ticket": ticket, "track": "M", "phase": "build",
}))

# ALLOWED on first ask.
out, _ = run("check", "--ticket", ticket, "--op", "get_hover_info",
             "--subject", "foo")
if not out.startswith("ALLOWED"):
    print("expected ALLOWED, got:", out, file=sys.stderr); sys.exit(1)

# save payload, then second check must be CACHED.
pl = pathlib.Path(".klc/tickets") / ticket / "payload.json"
pl.write_text(json.dumps({"signature": "foo(x: int) -> bool"}))
run("save", "--ticket", ticket, "--op", "get_hover_info",
    "--subject", "foo", "--payload", str(pl))
out, _ = run("check", "--ticket", ticket, "--op", "get_hover_info",
             "--subject", "foo")
if not out.startswith("CACHED "):
    print("expected CACHED, got:", out, file=sys.stderr); sys.exit(1)

# Track=XS must DENY everywhere.
(tdir / "meta.json").write_text(json.dumps({
    "ticket": ticket, "track": "XS", "phase": "build",
}))
out, _ = run("check", "--ticket", ticket, "--op", "get_hover_info",
             "--subject", "foo")
if not out.startswith("DENIED "):
    print("expected DENIED for XS, got:", out, file=sys.stderr); sys.exit(1)

# S/design DENY; S/build ALLOW (cache already present → CACHED).
(tdir / "meta.json").write_text(json.dumps({
    "ticket": ticket, "track": "S", "phase": "design",
}))
out, _ = run("check", "--ticket", ticket, "--op", "get_hover_info",
             "--subject", "foo")
if not out.startswith("DENIED "):
    print("expected DENIED for S/design, got:", out, file=sys.stderr); sys.exit(1)

# status must report counts > 0.
out, _ = run("status", "--ticket", ticket)
data = json.loads(out)
if data.get("cache_files", 0) < 1 or data.get("denied-track", 0) < 1:
    print("status counts off:", data, file=sys.stderr); sys.exit(1)
PY

# serena_deny skill: propose → add → list round-trip.
python3 - <<'PY' || fail "serena_deny.py round-trip failed"
import json, os, pathlib, subprocess, sys

env = os.environ.copy(); env["PROJECT_ROOT"] = os.getcwd()

# Manufacture cross-ticket call logs so `propose` has something to chew on.
for t in ("TICK-a", "TICK-b", "TICK-c"):
    d = pathlib.Path(".klc/tickets") / t
    d.mkdir(parents=True, exist_ok=True)
    rec = {"t": "2026-05-12T00:00:00Z", "event": "allowed",
           "op": "find_symbol", "subject": "AActor",
           "file": None, "line": None, "detail": ""}
    (d / "serena-calls.log").write_text(json.dumps(rec) + "\n")

def run(*args, expect_ok=True):
    r = subprocess.run(["python3", os.environ["KLC_FW"] + "/core/skills/serena_deny.py", *args],
                       capture_output=True, text=True, env=env)
    if expect_ok and r.returncode != 0:
        print("serena_deny", args, "exit", r.returncode, r.stderr, file=sys.stderr)
        sys.exit(1)
    return r.stdout, r.returncode

# Propose must surface AActor (present in 3 tickets).
out, _ = run("propose", "--min-tickets", "2")
if "AActor" not in out:
    print("propose did not surface AActor:", out, file=sys.stderr); sys.exit(1)

# Add the suggestion.
run("add", "--pattern", r"find_symbol\s+AActor", "--reason", "engine type")

# Project denylist must now show the entry.
out, _ = run("list")
if "AActor" not in out:
    print("list missing newly added pattern:", out, file=sys.stderr); sys.exit(1)

# Adding a duplicate must fail non-zero.
_, code = run("add", "--pattern", r"find_symbol\s+AActor",
              "--reason", "engine type", expect_ok=False)
if code == 0:
    print("duplicate pattern accepted", file=sys.stderr); sys.exit(1)

# Invalid regex must fail non-zero.
_, code = run("add", "--pattern", "(bad", "--reason", "x", expect_ok=False)
if code == 0:
    print("invalid regex accepted", file=sys.stderr); sys.exit(1)

# Propose must no longer surface the now-covered pattern.
out, _ = run("propose", "--min-tickets", "2")
if "AActor" in out:
    print("propose still lists covered entry:", out, file=sys.stderr); sys.exit(1)
PY

# items_verify skill: parses FACT headers, classifies, rewrites.
python3 - <<'PY' || fail "items_verify.py round-trip failed"
import json, os, pathlib, subprocess, sys, datetime as dt

env = os.environ.copy(); env["PROJECT_ROOT"] = os.getcwd()
tdir = pathlib.Path(".klc/tickets/TICK-fact")
tdir.mkdir(parents=True, exist_ok=True)

# Two real source files, referenced by FACT items.
src = pathlib.Path("src-fact"); src.mkdir(exist_ok=True)
stable = src / "stable.py"; stable.write_text("X = 1\n")
drift  = src / "drift.py";  drift.write_text("Y = 1\n")

# The fixture is not a git repo; items_verify needs git-tracked files
# to ask `git log --date=short`. Initialise a throw-away repo in CWD.
# The outer smoke may already have a .git, so don't re-init if present.
if not pathlib.Path(".git").exists():
    for cmd in [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name",  "t"],
    ]:
        subprocess.run(cmd, check=True, env=env)
e = env.copy()
for key, val in {
    "GIT_AUTHOR_DATE":    "2026-05-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-05-01T00:00:00Z",
}.items():
    e[key] = val
subprocess.run(["git", "add", "src-fact"], check=True, env=e)
subprocess.run(["git", "commit", "-q", "-m", "seed"], check=True, env=e)

(tdir / "spec.md").write_text("""
> [!FACT F-001] src=src-fact/stable.py:1 verified=2026-05-02
> Stable.

> [!FACT F-002] src=src-fact/drift.py:1 verified=2026-05-02
> Will drift.

> [!FACT F-003] verified=2026-05-02
> No src.
""", encoding="utf-8")
for key in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
    e[key] = "2026-05-02T00:00:00Z"
subprocess.run(["git", "add", ".klc"], check=True, env=e)
subprocess.run(["git", "commit", "-q", "-m", "spec"], check=True, env=e)

# Now drift the second file AFTER the verified date.
drift.write_text("Y = 99\n")
for key in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
    e[key] = "2026-05-10T00:00:00Z"
subprocess.run(["git", "add", "src-fact/drift.py"], check=True, env=e)
subprocess.run(["git", "commit", "-q", "-m", "drift"], check=True, env=e)

r = subprocess.run(
    ["python3", os.environ["KLC_FW"] + "/core/skills/items_verify.py", "scan", "--top", "10"],
    capture_output=True, text=True, env=env,
)
if r.returncode != 0:
    print("scan exit", r.returncode, r.stderr, file=sys.stderr); sys.exit(1)
summary = json.loads(r.stdout)
expected = {"confirmed": 1, "needs-review": 1, "undecidable": 1}
if summary.get("counts") != expected:
    print("expected counts", expected, "got", summary, file=sys.stderr); sys.exit(1)

# Header rewrite: F-001 → verified=<today>, F-002 → verified=stale-<today>.
today = dt.date.today().isoformat()
text = (tdir / "spec.md").read_text()
if f"F-001] src=src-fact/stable.py:1 verified={today}" not in text:
    print("F-001 not refreshed to today", file=sys.stderr); sys.exit(1)
if f"F-002] src=src-fact/drift.py:1 verified=stale-{today}" not in text:
    print("F-002 not marked stale", file=sys.stderr); sys.exit(1)
if "F-003] verified=2026-05-02" not in text:
    print("F-003 header was unexpectedly modified", file=sys.stderr); sys.exit(1)

# Log file exists and has at least 3 records from this scan.
log = pathlib.Path(".klc/knowledge/verification-log.jsonl")
if not log.exists():
    print("verification-log.jsonl missing", file=sys.stderr); sys.exit(1)
records = [json.loads(x) for x in log.read_text().splitlines() if x]
if len([r for r in records if r["id"] in {"F-001","F-002","F-003"}]) < 3:
    print("expected >= 3 records, got", records, file=sys.stderr); sys.exit(1)
PY

# scratch skill: new → list → read → archive round-trip.
python3 - <<'PY' || fail "scratch.py round-trip failed"
import json, os, pathlib, re, subprocess, sys
env = os.environ.copy(); env["PROJECT_ROOT"] = os.getcwd()
ticket = "TICK-smoke"

def run(*args):
    r = subprocess.run(["python3", os.environ["KLC_FW"] + "/core/skills/scratch.py", *args],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print("scratch.py", args, "exit", r.returncode, r.stderr, file=sys.stderr)
        sys.exit(1)
    return r.stdout

out = run("new", "--ticket", ticket, "--agent", "smoke",
         "--phase", "build", "--purpose", "verify scratch round-trip")
if not out.startswith("SCRATCH_NEW "):
    print("expected SCRATCH_NEW, got:", out, file=sys.stderr); sys.exit(1)
first = out.strip().split(" ", 1)[1]
if "001-" not in first:
    print("session numbering wrong:", first, file=sys.stderr); sys.exit(1)

# list must return the newly created file
listed = run("list", "--ticket", ticket).strip().splitlines()
if not any(first in line for line in listed):
    print("list missing new session:", listed, file=sys.stderr); sys.exit(1)

# read must include the SESSION envelope
read = run("read", "--ticket", ticket)
if "BEGIN SESSION 001-" not in read or "END SESSION 001-" not in read:
    print("read-back envelope missing", file=sys.stderr); sys.exit(1)

# archive moves scratch/ aside — must not leave the live dir
arc = run("archive", "--ticket", ticket).strip()
if not arc.startswith("SCRATCH_ARCHIVED "):
    print("archive did not run:", arc, file=sys.stderr); sys.exit(1)
live = pathlib.Path(".klc/tickets") / ticket / "scratch"
if live.exists():
    print("scratch/ still present after archive:", live, file=sys.stderr); sys.exit(1)
arc_dir = pathlib.Path(arc.split(" ", 1)[1])
if not any(p.name.startswith("001-") for p in arc_dir.iterdir()):
    print("archived session not preserved", file=sys.stderr); sys.exit(1)
PY

# klc phase loop — drive a synthetic ticket through every phase
# (XS track so we skip test-plan / design / manual). Phase 7 is
# simulated with a dummy merge-sha.
say "phase loop: intake → discover → build → review → integrate → observe → learn"

KLC="$SCRATCH/.klc/bin/klc"

# init a git repo so integrate and doctor don't complain.
git init -q
git config user.email t@t
git config user.name t
git add .
git commit -q -m "scratch init"

"$KLC" intake SMK-1 --kind feature "Verify phase loop end-to-end" >/dev/null
"$KLC" discover SMK-1 >/dev/null

TICKET_DIR="$SCRATCH/.klc/tickets/SMK-1"

# simulate discovery agent output: write spec + set XS track
cat > "$TICKET_DIR/spec.md" <<'EOF'
# SMK-1 — phase loop smoke
> [!FACT F-001] src=src/__init__.py:1 verified=2026-05-12
> Package exists.
## AC
1. AC-1: nothing crashes.
EOF
python3 - <<PY
import json, pathlib
p = pathlib.Path("$TICKET_DIR/meta.json")
m = json.loads(p.read_text())
m.update({"track":"XS","estimate":{"complexity":0,"uncertainty":0,"risk":0,"manual":0,"total":0},"layer":"code","affected_modules":[]})
p.write_text(json.dumps(m, indent=2))
PY

"$KLC" discover SMK-1 --continue >/dev/null
"$KLC" ack SMK-1 --for discovery >/dev/null
# XS → build-pending via ack; no test-plan / design
# Manually advance build-pending → review-pending via build
"$KLC" build SMK-1 >/dev/null
"$KLC" build SMK-1 --continue >/dev/null

# Skip live review (needs MCP) — advance phase manually
python3 $FW_ROOT/core/skills/lifecycle.py \
    advance --ticket SMK-1 --target review-pending-ack --note "smoke-skip-review" \
    >/dev/null 2>&1 || true
# Review-pending → review-pending-ack transition must be via ack gate;
# since we can't call live review.sh inside smoke, use lifecycle advance
# starting from review-pending:
python3 - <<PY
import json, os, sys, pathlib
sys.path.insert(0, '$FW_ROOT/core/skills')
os.environ["PROJECT_ROOT"] = "$SCRATCH"
import lifecycle
# Force through to review-pending-ack
p = pathlib.Path("$TICKET_DIR/meta.json")
m = json.loads(p.read_text())
if m.get("phase") == "review-pending":
    lifecycle.advance("SMK-1", "review-pending-ack", note="smoke-simulated-review-ok")
PY

"$KLC" ack SMK-1 --for review >/dev/null

# XS has manual=0 so review-pending-ack → integrate-pre
"$KLC" integrate pre SMK-1 >/dev/null
"$KLC" integrate post SMK-1 --merge-sha deadbeef --allow-drift >/dev/null

# Phase is now `learn` (integrate without --observe goes straight there)
# Write retrospective.md then learn --continue
cat > "$TICKET_DIR/retrospective.md" <<'EOF'
# retrospective
> [!FACT F-R01] src=meta.json
> smoke loop succeeded.
EOF
"$KLC" learn SMK-1 --continue >/dev/null

# Ticket should now be archived
[ -d "$SCRATCH/.klc/tickets/archive/SMK-1" ] || fail "archive dir missing"
[ -d "$SCRATCH/.klc/tickets/SMK-1" ] && fail "live ticket dir still present"

say "phase loop OK"
say "OK"
