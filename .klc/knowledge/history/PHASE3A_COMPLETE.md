# Phase 3a Complete — Risk-based review (tiers + sentinels)

## Summary

Phase 3a from the review overhaul plan is complete. Review pipeline now uses
risk-based tier classification (critical/core/peripheral) with per-tier blocking
thresholds, plus sentinel pattern detection that force-escalates high-risk code
to CRITICAL regardless of tier.

## Changes

### 3a.1 Tier classification config and skill
- `config/tiers.yml`:
  - Three-tier risk model:
    - **critical**: auth, crypto, payments, sessions, privilege escalation, core schemas
      - Blocking threshold: LOW (even LOW findings block merge)
      - Patterns: `**/*auth*/**`, `**/*crypto*/**`, `**/*payment*/**`, etc.
    - **core**: API endpoints, business logic, state machines, orchestrators, public APIs
      - Blocking threshold: HIGH (HIGH and CRITICAL block)
      - Patterns: `**/*api*/**`, `**/*service*/**`, `**/*handler*/**`, etc.
      - Auto-promoted: files exporting symbols in modules.json[].public_api
    - **peripheral**: tests, docs, scripts, tooling, UI polish, analytics
      - Blocking threshold: CRITICAL (only CRITICAL blocks)
      - Patterns: `**/tests/**`, `**/*.md`, `**/scripts/**`, `**/*.css`, etc.
  - Module metadata override: modules.json[].metadata.tier takes precedence
  - Fallback tier: peripheral

- `core/skills/classify_tier.py`:
  - CLI: `--diff <path> --format json|table`
  - Classification order:
    1. Module metadata tier override
    2. Path pattern match (fnmatch)
    3. Public API membership (symbols in public_api → core)
    4. Fallback (peripheral)
  - Output: `{files: [{path, tier, reason}], summary: {critical: N, core: M, peripheral: K}}`

### 3a.2 Sentinel pattern detection
- `config/sentinels.yml`:
  - 25 high-risk patterns across 6 categories:
    - **Code execution**: `eval()`, `exec()`, `vm.runInNewContext`, `Function()` constructor
    - **Deserialization**: `pickle.loads`, `yaml.load` (unsafe), `marshal.loads`
    - **Shell injection**: `shell=True`, `os.system()`, `child_process.exec(..., {shell:true})`
    - **SQL injection**: string concatenation in `execute()`, `%` formatting
    - **Secrets**: hard-coded API keys, passwords, AWS/GitHub/Slack/Stripe tokens
    - **Crypto misuse**: MD5 for security, ECB mode
    - **SSRF/TLS**: user-controlled URLs in `requests.get`, cert validation bypass (`verify=False`)
  - Each sentinel: id, regex pattern, description, language filter, severity_override (CRITICAL or HIGH)
  - Matches force verdict to CHANGES REQUESTED regardless of tier

- `core/skills/scan_sentinels.py`:
  - CLI: `--diff <path> --format json|table`
  - Parses unified diff into hunks (file + added lines only)
  - Matches sentinel regexes against added lines
  - Output: `{matches: [{sentinel_id, file, line, matched_text, description, severity_override}], summary: {total, critical, high}}`

### 3a.3 Per-tier blocking thresholds in review.py
- `scripts/review.py`:
  - **Before aggregation phase**:
    1. Run `classify_tier.py --diff <diff> --format json`
    2. Run `scan_sentinels.py --diff <diff> --format json`
    3. Build file → tier map
    4. Load tier thresholds from `config/tiers.yml`
  - **Tier-aware verdict logic**:
    - Replace simple `severity in (CRITICAL, HIGH)` with `_is_blocking(issue)` function
    - `_is_blocking()` checks:
      1. Is sentinel match? → always block
      2. Is out-of-scope? → never block
      3. Lookup file's tier from classification
      4. Compare issue.severity >= tier's blocking_threshold
    - Severity order: INFO < LOW < MEDIUM < HIGH < CRITICAL
  - **Sentinel injection**:
    - When sentinel matches exist, create synthetic CRITICAL findings
    - Add them to a "sentinels" pseudo-reviewer in `reviewers_data`
    - These findings always block (sentinel flag)
  - **reviewer_rows creation** moved after sentinel injection (so "sentinels" appears in summary table)
  - Pass `tier_classification` and `sentinel_matches` to template

### 3a.4 Review report template updates
- `core/templates/review-report.md.j2`:
  - **## Risk Tier Classification** section (when tier_classification exists):
    - Explains blocking threshold per tier (critical=LOW, core=HIGH, peripheral=CRITICAL)
    - Table: File | Tier | Reason
    - Summary: N critical, M core, K peripheral
  - **## Sentinel Patterns Detected** section (when matches exist):
    - Table: Sentinel ID | File:Line | Severity | Description
    - Total sentinel matches count
  - Both sections appear after ADRs and before Blocking Issues

## Acceptance criteria (all met)

1. ✅ `config/tiers.yml` defines three tiers with blocking thresholds and path patterns.
2. ✅ `classify_tier.py` classifies files in diff by tier (module metadata > pattern > public_api > fallback).
3. ✅ `config/sentinels.yml` defines 25+ high-risk patterns with severity overrides.
4. ✅ `scan_sentinels.py` detects sentinel patterns in diff (added lines only).
5. ✅ `review.py` applies per-tier blocking thresholds instead of simple CRITICAL+HIGH rule.
6. ✅ Sentinel matches inject synthetic CRITICAL findings and force-block.
7. ✅ Review report shows tier classification table and sentinel matches table.
8. ✅ "sentinels" reviewer appears in summary table when matches exist.

## Examples

**Critical-tier file with LOW finding:**
```
File: src/auth/jwt.py (tier: critical, reason: pattern match **/*auth*/**)
Finding: [LOW] Unused import 'datetime'
Result: BLOCKS merge (critical tier threshold is LOW)
```

**Core-tier file with MEDIUM finding:**
```
File: src/api/users.py (tier: core, reason: exports public_api symbol)
Finding: [MEDIUM] Missing input validation on 'email' field
Result: Does NOT block (core tier threshold is HIGH)
```

**Peripheral-tier file with sentinel match:**
```
File: scripts/deploy.sh (tier: peripheral, reason: pattern match **/scripts/**)
Sentinel: shell-true (line 42: subprocess.run(..., shell=True))
Result: BLOCKS merge (sentinel force-escalates to CRITICAL)
```

## Out of scope for Phase 3a

- Publish adapters (GitLab, GitHub) — Phase 3b.
- Cross-PR finding history — future.
- Hallucination detection skill — future.
- Module-level tier override in manifest.yml (config exists, but no UE-specific critical modules defined).

## Next steps

- **Phase 3b** — Publish adapters: GitLab and GitHub integration for:
  - MR/PR labels (APPROVED / CHANGES REQUESTED)
  - Inline comments on findings (file:line → review thread)
  - CI status checks (blocking when CHANGES REQUESTED)

## Testing recommendations

To test Phase 3a:

1. **Tier classification**:
   - Create diff touching `src/auth/login.py` (should be critical)
   - Create diff touching `tests/test_api.py` (should be peripheral)
   - Run `klc review --diff <branch> --spec <spec>`
   - Verify report shows tier classification table with correct tiers

2. **Sentinel detection**:
   - Add line `result = eval(user_input)` to a Python file
   - Run `klc review --diff <branch> --spec <spec>`
   - Verify report shows sentinel match for `eval-exec`
   - Verify verdict is CHANGES REQUESTED (even if file is peripheral)
   - Check "sentinels" reviewer appears in summary table

3. **Tier-aware thresholds**:
   - Create LOW finding in critical-tier file → should block
   - Create MEDIUM finding in core-tier file → should NOT block
   - Create HIGH finding in core-tier file → should block
   - Create MEDIUM finding in peripheral-tier file → should NOT block
   - Create CRITICAL finding in any tier → should always block

4. **False positive suppression**:
   - Add sentinel pattern in test file that's intentional (e.g., `eval()` in unit test for parser)
   - Add to `reviewer-allowlist.yml`: `pattern: "eval-exec"`, `reviewer: "sentinels"`
   - Verify finding is downgraded to INFO and doesn't block
