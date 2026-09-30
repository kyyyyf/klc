# KLC-127 replay fixtures — AC-21, AC-30

Redacted, one-shape copies of the real `code-review`/`external-review` findings
of KLC-133, KLC-137 and KLC-139, captured on 2026-09-30 from
`.klc/tickets/<ticket>/review/{code-review,external-review}-findings.json` on
`main`. These are the same findings discovery's P-3/P-4 probes (`design/options.md`,
`discovery/evidence.md`) paired and scored; this directory is the frozen, public
replay of that pairing (Q-101: fixtures are committed and mirrored to the public
gh repo).

This README is itself one of the files the redaction gate walks (no exemption,
unlike the KLC-133 README), so every redacted item below is described in prose
rather than quoted verbatim.

## Origin

| file | origin (read-only source) |
|---|---|
| `KLC-133-code-review-findings.json` | `.klc/tickets/KLC-133/review/code-review-findings.json` (4 findings) |
| `KLC-133-external-review-findings.json` | `.klc/tickets/KLC-133/review/external-review-findings.json` (4 findings) |
| `KLC-137-code-review-findings.json` | `.klc/tickets/KLC-137/review/code-review-findings.json` (3 findings) |
| `KLC-137-external-review-findings.json` | `.klc/tickets/KLC-137/review/external-review-findings.json` (6 findings) |
| `KLC-139-code-review-findings.json` | `.klc/tickets/KLC-139/review/code-review-findings.json` (5 findings) |
| `KLC-139-external-review-findings.json` | `.klc/tickets/KLC-139/review/external-review-findings.json` (7 findings) |

Every entry is mapped to the one Finding shape per spec.md's "Moved to KLC-154"
in-client mapping: `id` is `F-n` by position within its file, `rule_name` is
`legacy-unclassified` (the KLC-154 migration's own marker, D-118), `severity` is
upper-cased, and `reviewer`/`kind` are stamped with the file's own kind
(`code-review` or `external-review`). `ac`, `file`, `line`, `title`, `body` and
`fix` are the real reviewer's own words, unchanged apart from the redactions
below.

## Redactions (D-115, A-102: reword, never loosen the gate)

The redaction gate (`tests/integration/_klc133_support.forbidden_hits`, moved
here from `test_klc133_fixtures.py`) is unchanged and unweakened. Every hit it
found in the live corpus was fixed by rewording the finding text, not by
narrowing the gate:

- **KLC-133, finding 4 of both files** (the real fixture-redaction finding,
  code-review `F-4` / external-review `F-4`, both about a KLC-133 fixture
  leak): a real local scratch-capture directory path, holding a session
  identifier and a worker id, was replaced by a neutral placeholder path; the
  real worker id value was replaced by one placeholder token reused in both
  copies (so the pair's shared vocabulary barely moves); the two real proper
  nouns naming the organisation and the account holder became generic
  descriptions ("the org name", "the account holder's name"); every mention
  of the cryptographic-authentication-blob field name (both as a JSON key and
  in prose) was replaced by the shorter key `sig`; and the finding's own
  advice text, which quoted the two path-prefix patterns the redaction gate
  itself bans, was reworded to describe them generically ("a scratch-path
  prefix", "a home-directory-path prefix") so the fixture never repeats the
  literal substrings it is about.
- **KLC-137, external-review finding 4** (`F-4`, "Python ranges start at the
  `def`/`class` line and exclude decorators"): the three Python decorator
  names, each normally written with a leading at-sign punctuation mark, are
  spelled out as plain words instead ("the functools.lru_cache decorator",
  "the staticmethod decorator", "the property decorator", the last one twice)
  — the gate's blanket at-sign pattern stays exactly as strict as it is for
  every other fixture; only the decorator names' spelling changed, matching
  D-115.
- **KLC-137, code-review finding 3 / external-review finding 5** (`F-3`/`F-5`,
  the stale-docstring finding): the illustrative inline schema dict's
  cryptographic-authentication-blob field name (a real field of
  `core.shared.inventory`'s frozen schema, not a leaked secret, but a word the
  same blanket gate bans everywhere) was renamed to `sig` in both copies,
  consistently, so the pair's shared vocabulary is unaffected.
- **KLC-139, code-review finding 1** (`F-1`, the RecursionError finding): the
  literal repro command, which set a scratch-path environment variable before
  the real CLI invocation, was reworded to describe the same scratch
  redirection without quoting the path-prefix pattern.

No other finding in any of the six files matched the redaction gate.

## Recomputed similarity (A-102: the redaction must not move the 12-pair,
zero-false-merge margin)

Token-Jaccard over `title` plus the first 200 characters of `body`, lower-cased,
recomputed on the redacted text above with the exact `findings.similarity`
formula (step-7). `min_similarity` is 0.15 (`config/reviewers.yml`).

```text
true pairs (must be >= 0.15)                    j       (design/evidence.md pre-redaction j)
KLC-133  code-review:F-1 / external-review:F-1  0.212   (0.21)
KLC-133  code-review:F-2 / external-review:F-2  0.182   (0.21)
KLC-133  code-review:F-3 / external-review:F-3  0.220   (0.24)
KLC-133  code-review:F-4 / external-review:F-4  0.486   (0.42)
KLC-137  code-review:F-1 / external-review:F-3  0.432   (0.45)
KLC-137  code-review:F-2 / external-review:F-2  0.182   (0.17)
KLC-137  code-review:F-3 / external-review:F-5  0.326   (0.34)
KLC-139  code-review:F-1 / external-review:F-2  0.320   (0.39)
KLC-139  code-review:F-2 / external-review:F-1  0.500   (0.46)
KLC-139  code-review:F-3 / external-review:F-4  0.615   (0.58)
KLC-139  code-review:F-4 / external-review:F-3  0.357   (0.38)
KLC-139  code-review:F-5 / external-review:F-5  0.408   (0.41)

false pairs — KLC-139 skeleton.py lines 385-388, must stay < 0.15
(named code0/code1/code4/ext0/ext4 by test-plan.md, 0-based file position)
code-review:F-1 (code0) / code-review:F-2 (code1)         0.095   (0.10)
code-review:F-1 (code0) / code-review:F-5 (code4)         0.119   (0.09)
code-review:F-1 (code0) / external-review:F-1 (ext0)      0.098   (0.11)
code-review:F-1 (code0) / external-review:F-5 (ext4)      0.061   (0.07)
code-review:F-2 (code1) / code-review:F-5 (code4)         0.079   (0.07)
code-review:F-2 (code1) / external-review:F-5 (ext4)      0.050   (0.06)
code-review:F-5 (code4) / external-review:F-1 (ext0)      0.065   (0.06)
external-review:F-1 (ext0) / external-review:F-5 (ext4)   0.070   (0.08)
```

Lowest true pair: 0.182. Highest false pair: 0.119. The margin (pre-redaction:
lowest true 0.17, highest false 0.11, `discovery/evidence.md` P-4) moves by at
most 0.05 and never crosses — the A-102 assumption holds without rewording the
replacement tokens further.

## Replay result (AC-21)

Running `findings.py pool` (via `findings.group`) over the combined
code-review + external-review findings of each ticket gives, with zero false
merges:

```text
ticket    raw  pooled  merges
KLC-133    8     4       4
KLC-137    9     6       3
KLC-139   12     7       5
total     29    17      12
```

Each ticket's `<ticket>-pairs.json` file names every true pair as
`["<kind>:<id>", "<kind>:<id>"]` plus that ticket's `pooled_count`, read
directly by `tests/integration/test_klc127_replay.py` (step-8). All nine
files (three tickets times pairs/code-review/external-review) sit flat in
this one directory, not in per-ticket subdirectories — a fixture directory
that directly held files becomes its own module under `modules_build.py`'s
directory-level clustering (KLC-074), so nested per-ticket/per-kind
directories would have added six extra index modules for nothing; flat
naming keeps this fixture at the one module it needs (step-12, F-1/item 9).
