# Severity Rubric

This document defines the four severity levels used by all review agents.
When assigning severity to a finding, cite this rubric in your reasoning.

**General rule:** If uncertain between two levels, choose the lower one and
explain why in the finding body.

---

## CRITICAL

**Definition:** The change, if shipped, will cause immediate production
failure, data corruption, or a critical security vulnerability exploitable
by an external party.

**Examples:**

- **Auth bypass.** A code path allows unauthenticated access to a protected resource.
  ```python
  # CRITICAL: skips authentication check
  if user.is_authenticated or True:
      return protected_data()
  ```

- **Data corruption.** Missing transaction boundary or wrong SQL direction in a migration.
  ```sql
  -- CRITICAL: DROP without BEGIN TRANSACTION; irreversible data loss
  DROP TABLE users;
  ```

- **Remote code execution.** Direct `eval()` on user input, command injection via `shell=True`.
  ```python
  # CRITICAL: arbitrary code execution
  eval(request.GET['expr'])
  ```

**Non-examples:**

- A memory leak (HIGH, not CRITICAL — degrades over time but doesn't fail immediately).
- A reflected XSS (HIGH, not CRITICAL — requires user interaction to exploit).
- Missing input validation that could cause a crash (HIGH — availability impact, not data-integrity).

---

## HIGH

**Definition:** The change introduces a defect that:
- Breaks a documented contract (backwards-incompatible API change not mentioned in spec),
- Causes incorrect behavior in a production-critical path (payment calculation, order processing),
- Introduces a security vulnerability that requires user interaction or specific preconditions to exploit,
- Or violates an accepted ADR without rationale.

**Examples:**

- **Contract break.** Removing a public API method without a deprecation path.
  ```typescript
  // HIGH: processPayment() removed, no mention in spec
  export class PaymentService {
    // processPayment method deleted here
  }
  ```

- **Logic bug in critical path.** Off-by-one in a loop that processes financial records.
  ```python
  # HIGH: skips last transaction in batch
  for i in range(len(transactions) - 1):
      process(transactions[i])
  ```

- **Security (non-critical).** Stored XSS, CSRF on state-changing endpoints, missing rate limit on login.

- **ADR contradiction.** An ADR mandates sync flow; diff introduces async without rationale.

**Non-examples:**

- Naming inconsistency (MEDIUM — affects readability, not correctness).
- Missing test for an edge case (MEDIUM — the code may be correct, coverage is incomplete).
- Performance regression (MEDIUM or LOW depending on magnitude).

---

## MEDIUM

**Definition:** The change:
- Violates a documented convention or style guide in a way that affects maintainability,
- Introduces a potential bug that only manifests in edge cases,
- Degrades performance noticeably but does not break SLOs,
- Or adds technical debt that will require future remediation.

**Examples:**

- **Convention violation.** Inconsistent naming (camelCase in a snake_case codebase), missing type annotation in a fully-typed module.
  ```python
  # MEDIUM: breaks snake_case convention
  def ProcessOrder(order_id): ...
  ```

- **Edge-case bug.** Does not handle empty list, assumes non-null when null is possible, race condition under high concurrency.
  ```javascript
  // MEDIUM: crashes on empty cart
  const total = cart.items[0].price + ...
  ```

- **Performance.** N+1 query introduced, O(n²) where O(n) is feasible, no pagination on large dataset.

- **Tech debt.** Duplicates existing logic instead of refactoring, hardcodes a value that should be config, introduces a new global variable.

**Non-examples:**

- Unclear variable name in a 5-line function (LOW).
- Missing docstring on a private helper (LOW).
- Non-idiomatic code that is still correct and readable (LOW or INFO).

---

## LOW

**Definition:** The change:
- Reduces readability or clarity in a minor way,
- Violates style in a non-impactful context,
- Leaves an opportunity for improvement that is not urgent,
- Or is a subjective suggestion with no correctness or maintainability impact.

**Examples:**

- **Readability.** Unclear variable name (`x` instead of `user_count` in a 50-line function), deeply nested conditionals that could be flattened, magic number not extracted to a constant.

- **Style (minor).** Missing trailing comma in a list, inconsistent quote style in a single file.

- **Opportunity.** Could use a built-in function instead of manual loop, could combine two similar blocks, could add a helper that doesn't yet exist.

**Non-examples:**

- A typo in a comment (INFO, not LOW — does not affect code).
- Preference for a different library when both are equivalent (INFO — subjective, not actionable).

---

## Severity assignment checklist

Before assigning severity, ask:

1. **Does it break prod immediately or corrupt data?** → CRITICAL
2. **Does it break a contract, introduce a logic bug in a critical path, or violate an ADR?** → HIGH
3. **Does it violate a convention, introduce an edge-case bug, or degrade performance noticeably?** → MEDIUM
4. **Is it a minor readability or style issue with no correctness impact?** → LOW

When in doubt, downgrade and explain why the higher severity does not apply.

---

## Notes

- **INFO severity** (not listed above) is reserved for observations that are neither bugs nor violations — e.g., "this code is correct but there's a newer API available" or "consider X for future work." INFO findings never block.
- **Allowlisted findings** are downgraded to INFO by the aggregator after matching the allowlist.
- **Severity must be justified.** Each finding body should include "Severity rationale: …" citing this rubric.
