---
ticket: TEST-001
authority: agent
---

# Test Plan: Fake ticket

## Test scenarios

### TS-1: Happy path
**Priority**: P0  
**Preconditions**: None  
**Steps**:
1. Execute fake operation
2. Verify result

**Expected**: Success

## Acceptance coverage

| AC | Test scenarios |
|----|---------------|
| AC-1: Phase transitions | TS-1 |
| AC-2: Artefacts generated | TS-1 |

## Edge cases

- **EC-1**: Empty input → graceful handling

## Regression scenarios

None.

## Manual checklist

N/A (manual=0)
