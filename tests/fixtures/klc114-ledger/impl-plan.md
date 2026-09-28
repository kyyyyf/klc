---
ticket: KLC-114-LEDGER
kind: tech
authority: agent
---

# KLC-114-LEDGER — step ledger fixture (KLC-114 AC-12)

A 4-step fixture ticket, one step per verdict (A-202/C-102) — reproduces
`green`, `red`, `unverified` and `scope-violation` from one fabricated git
history, built by `tests/integration/test_klc114_fixture_e2e.py`. This
impl-plan text is frozen (`.klc/` is gitignored on the code branch, D-206);
the commits themselves are built fresh in the test.

## step-1 — the green step

- Goal: a clean, well-scoped, correctly-ordered step.
- RED: `tests/test_x.py::test_thing`
- GREEN: implement it
- VERIFY: `sh -c "echo 2 passed"`
- COMMIT: `KLC-114-LEDGER step-1: implement the green step`
- Affected: `core/skills/green.py`
- Interfaces: none
- Expected: `2 passed`
- Addresses: AC-1
- Depends on: none

```python
# sketch
pass
```

## step-2 — the red step

- Goal: an impl commit lands with no preceding failing-test commit for this step.
- RED: `tests/test_y.py::test_thing`
- GREEN: implement it
- VERIFY: `sh -c "echo 2 passed"`
- COMMIT: `KLC-114-LEDGER step-2: implement the red step`
- Affected: `core/skills/red.py`
- Interfaces: none
- Expected: `2 passed`
- Depends on: none

```python
# sketch
pass
```

## step-3 — the unverified step

- Goal: no commit in this fixture's fabricated history carries this step's key.
- RED: `tests/test_z.py::test_thing`
- GREEN: implement it
- VERIFY: `sh -c "echo 2 passed"`
- COMMIT: `KLC-114-LEDGER step-3: implement the unverified step`
- Affected: `core/skills/unverified.py`
- Interfaces: none
- Expected: `2 passed`
- Depends on: none

```python
# sketch
pass
```

## step-4 — the scope-violation step

- Goal: a commit touches a path outside the step's declared surface.
- RED: `tests/test_w.py::test_thing`
- GREEN: implement it
- VERIFY: `sh -c "echo 2 passed"`
- COMMIT: `KLC-114-LEDGER step-4: implement the scope-violation step`
- Affected: `core/skills/scoped.py`
- Interfaces: none
- Expected: `2 passed`
- Depends on: none

```python
# sketch
pass
```
