---
ticket: KLC-010
authority: hybrid
last_generated: 2026-05-29T01:30:00Z
reviewers:
  - architecture
  - performance
  - test-coverage
---

# Code Review Report — KLC-010

## Summary

**Changeset**: 19 files, +2235/-320 lines  
**Reviewers**: 3 sub-agents (architecture, performance, test-coverage)  
**Total Issues**: 24 (4 BLOCKING, 9 MEDIUM, 11 LOW/INFO)  
**Verdict**: **APPROVE WITH CONDITIONS** (fix 4 blocking issues before merge)

---

## Architecture Review (6 issues, 1 blocking)

### BLOCKING

**[ARCH-1] HIGH: Backup file committed to repository**
- **File**: `scripts/install_deps.py.bak`
- **Issue**: 342-line backup file should not be committed
- **Fix**: Remove from commit, add `*.bak` to `.gitignore`

### MEDIUM

**[ARCH-2] Undeclared external dependency - PyYAML**
- **File**: `core/skills/detect_languages.py:88`
- **Issue**: `import yaml` used but PyYAML not checked in bootstrap/project deps
- **Impact**: `klc setup` silently skips profile.yml if PyYAML missing
- **Fix**: Add PyYAML to project dependencies or document requirement

**[ARCH-3] Hardcoded tool registry creates maintenance burden**
- **File**: `core/phases/setup.py:32-88`
- **Issue**: `TOOLS_BY_LANG` duplicates tool info from `core/deps/*`
- **Impact**: Must update multiple files when adding/removing tools
- **Fix**: Extract to shared config (`config/tools-registry.yml`) or query deps modules

**[ARCH-4] Silent import fallback may hide configuration errors**
- **File**: `core/deps/project.py:105-113`
- **Issue**: Falls back to no-op lambdas when `tools.py` import fails
- **Impact**: Visual Studio clangd auto-detection fails silently
- **Fix**: Log warning when falling back

### LOW

**[ARCH-5] Hardcoded constants lack configuration override**
- **File**: `detect_languages.py:50`, `setup.py:32`
- **Issue**: `FILE_COUNT_THRESHOLD=10` and tool lists not overridable via profile
- **Fix**: Allow profile.yml overrides for thresholds and tool lists

**[ARCH-6] Complex conditional logic for warn flag**
- **File**: `core/phases/doctor.py:264-274`
- **Issue**: Special-case `--strict` handling adds branching complexity
- **Fix**: Refactor to decorator metadata system

### POSITIVE

- ✅ Clean module boundaries, no circular imports
- ✅ Backward compatibility preserved
- ✅ Proper command registration
- ✅ Good test coverage (28 tests)
- ✅ Graceful degradation (missing files don't crash)

---

## Performance Review (6 issues, 1 blocking)

### BLOCKING

**[PERF-1] HIGH: Excessive subprocess calls in ast-grep rule validation**
- **File**: `core/deps/project.py:153-159`
- **Issue**: N+1 pattern - one `subprocess.run` per YAML rule file
- **Impact**: 150-900ms overhead (3 rules × 50-300ms each)
- **Fix**: Batch validation - invoke ast-grep once with multiple `--rule` flags

### MEDIUM

**[PERF-2] File I/O on every log() call**
- **File**: `core/deps/__init__.py:25-31`
- **Issue**: Opens/closes log file for each log statement (12+ calls)
- **Impact**: 12-60ms per run
- **Fix**: Keep file handle open or buffer in memory

**[PERF-3] Double vswhere.exe calls for clangd detection**
- **File**: `core/deps/project.py:37-81`
- **Issue**: Two subprocess calls with 10s timeout each (Windows only)
- **Impact**: 200-1000ms on Windows
- **Fix**: Combine into single vswhere call, filter in Python

**[PERF-4] Profile-resolve.py subprocess**
- **File**: `core/deps/project.py:140-146`
- **Issue**: Spawns Python subprocess instead of importing as module
- **Impact**: 50-150ms interpreter startup overhead
- **Fix**: Import profile-resolve.py as module

### LOW

**[PERF-5] Sequential shutil.which calls in setup.py**
- **File**: `core/phases/setup.py:115-117`
- **Issue**: 15-20 sequential PATH lookups
- **Impact**: 30-75ms (acceptable)
- **Fix**: Parallelize with ThreadPoolExecutor if needed

**[PERF-6] Multiple file reads without caching**
- **File**: `detect_languages.py:65,89`, `doctor.py:234`
- **Issue**: inventory.json, profile.yml, project-deps.json read every invocation
- **Impact**: 10-60ms (acceptable for infrequent commands)
- **Fix**: Add caching if commands become frequent

### SUMMARY

**Total overhead**: 400-1200ms for full project dependency check

**Bottlenecks**:
1. ast-grep validation: 150-900ms (HIGH)
2. vswhere on Windows: 200-1000ms (MEDIUM)
3. Log file I/O: 12-60ms (MEDIUM)
4. profile-resolve subprocess: 50-150ms (LOW)

---

## Test Coverage Review (12 issues, 2 blocking)

### BLOCKING

**[TEST-1] HIGH: Language detection threshold boundary cases not tested**
- **Module**: `detect_languages.py`, AC-4
- **Issue**: Threshold `FILE_COUNT_THRESHOLD=10` not tested at boundaries (9/10/11 files)
- **Risk**: Boundary regressions could go undetected
- **Fix**: Add tests for 9 files (no detect), 10 files (detect), 11 files (detect)

**[TEST-2] HIGH: Malformed JSON/YAML error handling not tested**
- **Module**: `detect_languages.py`, `setup.py`, `doctor.py`, AC-4/5/6
- **Issue**: Try-except blocks for malformed input not exercised
- **Risk**: Production failures on corrupted files
- **Fix**: Test invalid JSON/YAML in inventory, profile, project-deps

### MEDIUM

**[TEST-3] Dispatcher flag conflicts not tested**
- **Module**: `install_deps.py`, AC-1/2/3
- **Issue**: `--bootstrap --dev`, `--bootstrap --strict` combinations not tested
- **Fix**: Test flag precedence and invalid combinations

**[TEST-4] Empty/missing file edge cases**
- **Module**: `detect_languages.py`, `setup.py`, AC-4/5
- **Issue**: Empty JSON (`{}`), empty profile, missing files partially tested
- **Fix**: Comprehensive empty/missing tests for all modules

**[TEST-5] Doctor check ordering not validated**
- **Module**: `doctor.py`, AC-6, constraint C-004
- **Issue**: Test expects 8 checks but spec says 10 (missing reviewer-allowlist, jira-sync-queue)
- **Fix**: Validate all 10 checks run in correct order

**[TEST-6] init output format not validated**
- **Module**: `init.py`, AC-7
- **Issue**: Tests check substring presence but not exact format ("1. klc setup", "2. klc doctor")
- **Fix**: Validate numbering and full message format

**[TEST-7] ImportError fallbacks not tested**
- **Module**: All modules with import fallbacks
- **Issue**: `try/except ImportError` blocks not exercised
- **Fix**: Mock import failures and validate graceful degradation

### LOW/INFO

**[TEST-8]** Tool detection edge cases (alt names, paths with spaces)  
**[TEST-9]** README validation (AC-9)  
**[TEST-10]** `klc setup --json` flag not tested  
**[TEST-11]** Mock side effects (logging, file writes) not validated  
**[TEST-12]** Deprecated `--project` flag handling not tested

### SUMMARY

- **Happy path coverage**: Excellent (28 tests, all ACs covered)
- **Edge case coverage**: Good (some boundaries tested)
- **Error path coverage**: Weak (malformed input, import failures not tested)
- **Integration coverage**: Good (doctor, setup, init integration tests)

---

## Aggregate Verdict

### Blocking Issues (Must Fix Before Merge)

1. **[ARCH-1]** Remove `scripts/install_deps.py.bak` from commit
2. **[PERF-1]** Fix ast-grep N+1 subprocess pattern
3. **[TEST-1]** Add threshold boundary tests (9/10/11 files)
4. **[TEST-2]** Add malformed JSON/YAML error handling tests

### Recommended Fixes (Should Fix Before Merge)

5. **[ARCH-2]** Document or check PyYAML dependency
6. **[PERF-2]** Buffer log file writes
7. **[PERF-3]** Optimize Windows vswhere calls
8. **[TEST-3]** Test dispatcher flag conflicts
9. **[TEST-4]** Test empty/missing file edge cases
10. **[TEST-5]** Fix doctor check count validation

### Optional Improvements (Nice to Have)

11. **[ARCH-3]** Extract tool registry to config
12. **[ARCH-4]** Log warning on tools.py import failure
13. **[PERF-4]** Import profile-resolve.py as module
14. **[TEST-6..12]** Additional test coverage for edge cases

---

## Verdict

**APPROVE WITH CONDITIONS**

The refactoring successfully modularizes dependency checking with clean separation of concerns (bootstrap/dev/project). Architecture is solid, test coverage is comprehensive for happy paths, and regression tests pass.

**Before merge, fix 4 blocking issues:**
1. Remove .bak file
2. Fix ast-grep subprocess N+1
3. Add threshold boundary tests
4. Add malformed input tests

**Estimated effort**: 2-3 hours to fix blocking issues.

Once blocking issues are resolved, this change is ready for integration.

---

## Reviewers Sign-Off

- **Architecture Review**: 6 findings (1 HIGH, 2 MEDIUM, 3 LOW)
- **Performance Review**: 6 findings (1 HIGH, 3 MEDIUM, 2 LOW)
- **Test Coverage Review**: 12 findings (2 HIGH, 5 MEDIUM, 5 LOW/INFO)

**Total**: 24 findings, 4 blocking

---

**Generated**: 2026-05-29T01:30:00Z  
**Review Duration**: ~3 minutes (parallel reviewer agents)  
**Next Phase**: Manual testing → Integrate
