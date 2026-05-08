#!/usr/bin/env bash
# install-deps.sh — check and (where possible) install all framework dependencies.
#
# Exits 0 if every dependency is already present or was installed.
# Exits 1 if at least one dependency is missing and cannot be installed automatically.
# In that case it prints manual installation instructions to stderr.
#
# All output is English.

set -uo pipefail

FRAMEWORK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${FRAMEWORK_ROOT}/logs/install-deps.log"
mkdir -p "${FRAMEWORK_ROOT}/logs"

missing=()
suggestions=()

log()  { echo "[install-deps] $*" | tee -a "${LOG_FILE}"; }
warn() { echo "[install-deps][warn] $*" | tee -a "${LOG_FILE}" >&2; }
err()  { echo "[install-deps][err]  $*" | tee -a "${LOG_FILE}" >&2; }

have() { command -v "$1" >/dev/null 2>&1; }

# Detect platform (best-effort). On Windows under Git Bash, $OSTYPE is msys/cygwin.
detect_platform() {
  case "${OSTYPE:-}" in
    linux-gnu*) echo "linux" ;;
    darwin*)    echo "macos" ;;
    msys*|cygwin*|win32) echo "windows" ;;
    *)          echo "unknown" ;;
  esac
}
PLATFORM="$(detect_platform)"
log "Platform detected: ${PLATFORM}"

check() {
  local name="$1"; shift
  local hint="$1";  shift
  if have "$name"; then
    log "  ok  ${name} ($(command -v "$name"))"
    return 0
  fi
  missing+=("$name")
  suggestions+=("${name}: ${hint}")
  warn "  missing  ${name}"
}

# --- core tools ---------------------------------------------------------------
log "Checking core tools"
check git     "install git from https://git-scm.com"
check jq      "install jq: apt install jq | brew install jq | choco install jq"
check python3 "install Python 3.10+ from https://python.org (on Windows 'python' works too)"
if ! have python3 && have python; then
  log "  note  'python' present, using it as python3 alias"
fi
check node    "install Node.js LTS from https://nodejs.org"
check npm     "npm ships with Node.js"

# --- ast-grep -----------------------------------------------------------------
log "Checking ast-grep"
if have ast-grep || have sg; then
  log "  ok  ast-grep"
  # Validate every rule the active profile pulls in. A single broken rule
  # silently breaks downstream agents that rely on ast-grep, so surface it.
  rule_failures=0
  tmpdir=$(mktemp -d)
  : > "$tmpdir/empty.cpp"; : > "$tmpdir/empty.py"; : > "$tmpdir/empty.ts"; : > "$tmpdir/empty.rs"
  rule_dirs=$(python3 framework/core/skills/profile-resolve.py --field rules)
  for rd in $rule_dirs; do
    for rf in framework/$rd/*.yaml; do
      [ -f "$rf" ] || continue
      if ! ast-grep scan --rule "$rf" "$tmpdir" >/dev/null 2>&1; then
        warn "  broken rule: $rf"
        rule_failures=$((rule_failures + 1))
      fi
    done
  done
  rm -rf "$tmpdir"
  if [ "$rule_failures" -gt 0 ]; then
    missing+=("ast-grep-rules")
    suggestions+=("ast-grep: $rule_failures rule file(s) fail to parse under ast-grep $(ast-grep --version | awk '{print $2}'). Quote inline patterns containing ':' or rewrite them to match a single AST node.")
  fi
else
  missing+=("ast-grep")
  suggestions+=("ast-grep: npm i -g @ast-grep/cli  OR  cargo install ast-grep --locked  OR  brew install ast-grep")
  warn "  missing  ast-grep"
fi

# --- uv (Python package manager) ---------------------------------------------
log "Checking uv"
check uv "install uv: https://docs.astral.sh/uv/  (curl -LsSf https://astral.sh/uv/install.sh | sh)"

# --- LSP servers --------------------------------------------------------------
log "Checking LSP servers (optional per language)"
if have pylsp; then log "  ok  pylsp"; else
  missing+=("pylsp"); suggestions+=("pylsp: pipx install 'python-lsp-server[all]'  OR  uv tool install python-lsp-server")
  warn "  missing  pylsp"
fi
if have typescript-language-server; then log "  ok  typescript-language-server"; else
  missing+=("typescript-language-server"); suggestions+=("typescript-language-server: npm i -g typescript-language-server typescript")
  warn "  missing  typescript-language-server"
fi
check clangd        "install clangd: apt install clangd | brew install llvm | choco install llvm"
check rust-analyzer "install rust-analyzer: rustup component add rust-analyzer"

# --- dep-graph tools ----------------------------------------------------------
log "Checking dep-graph tools"
if have madge; then log "  ok  madge"; else
  missing+=("madge"); suggestions+=("madge: npm i -g madge")
  warn "  missing  madge"
fi
if have pipdeptree; then log "  ok  pipdeptree"; else
  missing+=("pipdeptree"); suggestions+=("pipdeptree: pipx install pipdeptree  OR  uv tool install pipdeptree")
  warn "  missing  pipdeptree"
fi
check cargo  "install Rust toolchain for 'cargo metadata'"
check cmake  "install cmake for C++ dep-graph (optional, only if the project uses CMake)"

# --- Python libraries required by framework skills ---------------------------
log "Checking Python libraries (jinja2)"
PY="python3"
have "$PY" || PY="python"
if "$PY" -c "import jinja2" >/dev/null 2>&1; then
  log "  ok  jinja2"
else
  warn "  missing  python jinja2 module"
  suggestions+=("jinja2: ${PY} -m pip install jinja2  OR  uv pip install jinja2")
  missing+=("jinja2")
fi

# --- mutation testing tools ---------------------------------------------------
log "Checking mutation testing tools (optional per language)"
if have mutmut; then log "  ok  mutmut"; else
  missing+=("mutmut"); suggestions+=("mutmut: pip install mutmut  OR  pipx install mutmut  OR  uv tool install mutmut")
  warn "  missing  mutmut"
fi
if have stryker; then log "  ok  stryker"; else
  missing+=("stryker"); suggestions+=("stryker: npm install -g @stryker-mutator/core")
  warn "  missing  stryker"
fi
if have cargo-mutants; then log "  ok  cargo-mutants"; else
  missing+=("cargo-mutants"); suggestions+=("cargo-mutants: cargo install cargo-mutants")
  warn "  missing  cargo-mutants"
fi
# mull requires LLVM; we only print instructions.
if have mull-runner; then
  log "  ok  mull-runner"
else
  warn "  missing  mull-runner (C++ mutation testing)"
  warn "    install: https://github.com/mull-project/mull (requires LLVM)"
fi

# --- summary ------------------------------------------------------------------
echo
if [ "${#missing[@]}" -eq 0 ]; then
  log "All dependencies present."
  exit 0
fi

err "Missing dependencies: ${missing[*]}"
err "Manual installation suggestions:"
for s in "${suggestions[@]}"; do err "  - $s"; done
err ""
err "After installing, re-run: ./framework/scripts/install-deps.sh"
exit 1
