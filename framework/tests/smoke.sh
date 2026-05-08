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
# Usage:   framework/tests/smoke.sh [--keep]
#   --keep  leave the scratch dir behind for inspection.

set -eu

KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

FW_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$FW_ROOT/.." && pwd)"
FIXTURE="$FW_ROOT/tests/fixtures/tiny-py"

if [ ! -d "$FIXTURE" ]; then
  echo "smoke: fixture missing at $FIXTURE" >&2; exit 2
fi

SCRATCH="$(mktemp -d)"
cleanup() { [ "$KEEP" = "1" ] || rm -rf "$SCRATCH"; }
trap cleanup EXIT

cp -a "$FIXTURE/." "$SCRATCH/"
# Fresh framework — copy the live one but scrub runtime artefacts.
rsync -a --exclude='index/*' --exclude='logs/*' --exclude='reports/*' \
  --exclude='.last-run' --exclude='__pycache__' --exclude='*.pyc' \
  "$FW_ROOT/" "$SCRATCH/framework/"
: > "$SCRATCH/framework/index/.gitkeep"
echo "profile: generic" > "$SCRATCH/framework/config/profile.yml"

cd "$SCRATCH"

say() { printf '[smoke] %s\n' "$*"; }
fail() { printf '[smoke] FAIL: %s\n' "$*" >&2; [ "$KEEP" = "1" ] && printf '[smoke] scratch preserved at %s\n' "$SCRATCH" >&2; exit 1; }

say "scratch: $SCRATCH"

say "1/4 file-scanner.sh"
bash framework/core/skills/file-scanner.sh > framework/index/structural.json
python3 -c "import json; json.load(open('framework/index/structural.json'))" \
  || fail "structural.json did not parse"

say "2/4 dep-graph.sh"
bash framework/core/skills/dep-graph.sh > framework/index/depgraph.json
python3 -c "
import json, sys
d = json.load(open('framework/index/depgraph.json'))
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

struct = json.loads(pathlib.Path("framework/index/structural.json").read_text())
dep    = json.loads(pathlib.Path("framework/index/depgraph.json").read_text())

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
pathlib.Path("framework/index/inventory.json").write_text(json.dumps(inventory, indent=2))
pathlib.Path("framework/index/modules.json").write_text(json.dumps({
    "generated_at": inventory["generated_at"],
    "git_sha":      "smoke",
    "modules":      modules,
    "cycles":       [],
    "notes":        [],
}, indent=2))
PY

say "4/4 public-api-filter + module-writer --all"
python3 framework/core/skills/public-api-filter.py
python3 framework/core/skills/module-writer.py --all > /dev/null

[ -f CLAUDE.md ] || fail "root CLAUDE.md not written"
# Every module must end up with its own CLAUDE.md
python3 - <<'PY' || fail "per-module CLAUDE.md missing"
import json, pathlib, sys
mods = json.loads(pathlib.Path("framework/index/modules.json").read_text()).get("modules", [])
missing = []
for m in mods:
    doc = pathlib.Path(m["path"]) / (m.get("doc_filename") or "CLAUDE.md")
    if not doc.exists():
        missing.append(str(doc))
if missing:
    print("missing module CLAUDE.md files:", missing, file=sys.stderr); sys.exit(1)
PY

say "OK"
