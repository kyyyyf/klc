# KLC-110 retrieval baseline

This is the pre-KLC-108 baseline table `planning-eval.py --backfill` produces (KLC-110
AC-17/AC-18): the whole klc ticket corpus, scored twice — once from the trace `stored`
at intake, once from a trace `replayed` against the current index using that trace's
own recorded query — with the two populations **never pooled into one mean** (D-218).

- **measured**: 2026-09-25T11:14:33Z (regenerated at review round 1, step-11c)
- **index generation**: `2026-09-25T11:14:15Z` (`.klc/index/modules.json:generated_at`)
- **corpus**: 115 ticket directories under `.klc/tickets/` with a `meta.json` (grown by one
  since the original 2026-09-20 measurement — ordinary ticket-archive growth, not a
  methodology change)
- **availability**: `stored` — 6 scored, 109 unavailable (every stored `retrieval_trace.json`
  on this repository predates KLC-106's coverage cap and is `status: "unavailable"` except
  the six most recently intaken tickets); `replayed` — 115 scored, 0 unavailable (every
  ticket carries a recorded query or a `raw.md`, so `rescore_trace` always has something to
  run against the current index).
- **regenerated with**: `python3 core/skills/planning-eval.py --backfill --trace-source both
  --tickets .klc/tickets --out <scratch>/klc110-backfill-r1.json --out-md
  <scratch>/klc110-backfill-r1.md` (run read-only over the live corpus and the live index;
  `--out`/`--out-md` point at a scratch directory, never the live `.klc/index/`, per step-11b's
  new `--out-md` requirement — the rendered output was then copied into this committed file).

## The reference points

**This section is hand-authored and MUST be preserved verbatim on any future regeneration** —
`render_backfill()` only produces the "The rendered table" section below; the reference points
and the sentence on why the spec-pinned number is unused are written by a human/agent reading
`.klc/tickets/KLC-108/measure/before_after_full_corpus.json`, not by the backfill command itself.

- **KLC-108's like-for-like AFTER measurement, `0.2414`** — `mean_precision_at_5` from the
  `undegraded_variant.after` block of
  `.klc/tickets/KLC-108/measure/before_after_full_corpus.json` (111-ticket corpus, both
  BEFORE and AFTER retrievers replayed against the identical committed tree so the only
  variable is the retriever/rules code). This is the number KLC-108 itself was graded
  against, and the number a future retriever change should be diffed against.
- **The pre-KLC-108 historical figure, `0.1964`** — `undegraded_variant.before.mean_precision_at_5`
  from the same file: the OLD (pre-KLC-108) retriever replayed over the identical 111-ticket
  corpus and ground truth the AFTER run used, so the two are apples-to-apples (KLC-108's own
  drift-review F-1 finding: comparing a 3-ticket BEFORE probe against a 110/111-ticket AFTER
  mean was not).
- **The spec-pinned `0.1333` is not used as a baseline anywhere in this document.** It is a
  3-ticket probe number from a different vintage of the retriever (`spec.md`'s own citation),
  not a corpus-wide measurement — exactly the apples-to-oranges comparison KLC-108's drift
  review already flagged and re-measured as the `0.1964`/`0.2414` pair above. This backfill's
  own `replayed` mean (below) is a THIRD measurement, over the full current 115-ticket corpus
  against TODAY's index, and is expected to differ from both KLC-108 figures for that reason
  — it is not a discrepancy, it is a larger and more current corpus.
- **Review round 1 (2026-09-25) note**: this regeneration's own `replayed` precision@5 mean
  moved from `0.2456` (114-ticket corpus, 2026-09-20 index) to `0.2487` (115-ticket corpus,
  2026-09-25 index) — one additional archived ticket plus a regenerated live index, not a
  change caused by any of review round 1's code fixes (steps 8–11 touch the `affected_modules_
  hint` arrow, meta-patch lifecycle, trace-field robustness, and colocated-test confirmation —
  none of which `backfill_rows()` scores; it computes only `precision_at_5`/`recall_at_10` over
  `files_likely_to_edit`/`files_to_read_first`).

## The rendered table


- measured: 2026-09-25T11:14:33.140340+00:00
- index generation: 2026-09-25T11:14:15Z

## stored

- tickets total: 115
- tickets scored: 6
- tickets unavailable: 109
- precision@5 mean: 0.16666666666666666
- recall@10 mean: 0.02173432214415821

| ticket | status | confidence | derivation_source | derivation_confidence | precision@5 | recall@10 |
|---|---|---|---|---|---|---|
| KLC-001 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-003 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-004 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-005 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-006 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-007 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-008 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-009 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-010 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-011 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-012 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-014 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-015 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-016 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-017 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-018 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-019 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-02 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-020 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-021 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-022 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-034 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-035 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-036 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-037 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-038 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-039 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-040 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-041 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-042 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-043 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-044 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-045 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-046 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-047 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-048 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-049 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-050 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-051 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-052 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-053 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-054 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-055 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-056 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-057 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-058 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-059 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-060 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-061 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-062 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-063 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-064 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-065 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-066 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-067 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-068 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-069 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-070 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-071 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-072 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-073 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-074 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-075 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-076 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-077 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-078 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-079 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-080 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-081 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-082 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-083 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-084 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-085 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-086 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-087 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-088 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-089 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-090 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-091 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-092 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-093 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-094 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-095 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-096 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-097 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-098 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-099 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-100 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-101 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-102 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-103 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-104 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-105 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-106 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-107 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-108 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-109 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-110 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-111 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-112 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-113 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-114 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-115 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-116 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-117 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-118 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-119 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-120 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-121 | unavailable |  | git-log-grep | best-effort |  |  |
| KLC-122 | ok | high | git-log-grep | best-effort | 0.4 | 0.025 |
| KLC-123 | ok | low | git-log-grep | best-effort | 0.2 | 0.03278688524590164 |
| KLC-124 | ok | low | git-log-grep | best-effort | 0.2 | 0.047619047619047616 |
| KLC-125 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-126 | ok | medium | git-log-grep | best-effort | 0.2 | 0.025 |
| KLC-127 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |

## replayed

- tickets total: 115
- tickets scored: 115
- tickets unavailable: 0
- precision@5 mean: 0.24869565217391307
- recall@10 mean: 0.09623902963056884

| ticket | status | confidence | derivation_source | derivation_confidence | precision@5 | recall@10 |
|---|---|---|---|---|---|---|
| KLC-001 | ok | high | git-log-grep | best-effort | 0.2 | 0.2 |
| KLC-003 | ok | medium | git-log-grep | best-effort | 0.2 | 0.06666666666666667 |
| KLC-004 | ok | medium | git-log-grep | best-effort | 0.2 | 0.125 |
| KLC-005 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-006 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-007 | ok | medium | git-log-grep | best-effort | 0.8 | 0.10416666666666667 |
| KLC-008 | ok | medium | git-log-grep | best-effort | 0.2 | 0.058823529411764705 |
| KLC-009 | ok | medium | git-log-grep | best-effort | 0.2 | 0.038461538461538464 |
| KLC-010 | ok | medium | git-log-grep | best-effort | 0.2 | 0.045454545454545456 |
| KLC-011 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-012 | ok | medium | git-log-grep | best-effort | 0.2 | 0.2 |
| KLC-014 | ok | medium | git-log-grep | best-effort | 0.4 | 0.3333333333333333 |
| KLC-015 | ok | medium | git-log-grep | best-effort | 0.2 | 0.16666666666666666 |
| KLC-016 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-017 | ok | medium | git-log-grep | best-effort | 0.2 | 0.14285714285714285 |
| KLC-018 | ok | medium | git-log-grep | best-effort | 0.6 | 0.22727272727272727 |
| KLC-019 | ok | medium | git-log-grep | best-effort | 0.0 | 0.25 |
| KLC-02 | ok | medium | git-log-grep | best-effort | 0.2 | 0.058823529411764705 |
| KLC-020 | ok | medium | git-log-grep | best-effort | 1.0 | 0.35714285714285715 |
| KLC-021 | ok | medium | git-log-grep | best-effort | 0.6 | 0.2727272727272727 |
| KLC-022 | ok | medium | git-log-grep | best-effort | 0.4 | 0.5 |
| KLC-034 | ok | medium | git-log-grep | best-effort | 0.2 | 0.18181818181818182 |
| KLC-035 | ok | medium | git-log-grep | best-effort | 0.0 | 0.06666666666666667 |
| KLC-036 | ok | medium | git-log-grep | best-effort | 0.4 | 0.09523809523809523 |
| KLC-037 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-038 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-039 | ok | medium | git-log-grep | best-effort | 0.4 | 0.25 |
| KLC-040 | ok | medium | git-log-grep | best-effort | 0.0 | 0.1 |
| KLC-041 | ok | medium | git-log-grep | best-effort | 0.4 | 0.13636363636363635 |
| KLC-042 | ok | medium | git-log-grep | best-effort | 0.4 | 0.13333333333333333 |
| KLC-043 | ok | medium | git-log-grep | best-effort | 0.2 | 0.3333333333333333 |
| KLC-044 | ok | medium | git-log-grep | best-effort | 0.2 | 0.07692307692307693 |
| KLC-045 | ok | medium | git-log-grep | best-effort | 0.4 | 0.16666666666666666 |
| KLC-046 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-047 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-048 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-049 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-050 | ok | medium | git-log-grep | best-effort | 0.6 | 0.1875 |
| KLC-051 | ok | medium | git-log-grep | best-effort | 0.4 | 0.2 |
| KLC-052 | ok | medium | git-log-grep | best-effort | 0.2 | 0.014492753623188406 |
| KLC-053 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-054 | ok | high | git-log-grep | best-effort | 0.2 | 0.5 |
| KLC-055 | ok | medium | git-log-grep | best-effort | 0.2 | 0.2 |
| KLC-056 | ok | medium | git-log-grep | best-effort | 0.2 | 0.5 |
| KLC-057 | ok | medium | git-log-grep | best-effort | 0.4 | 0.09523809523809523 |
| KLC-058 | ok | medium | git-log-grep | best-effort | 0.4 | 0.25 |
| KLC-059 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-060 | ok | medium | git-log-grep | best-effort | 0.2 | 0.16666666666666666 |
| KLC-061 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-062 | ok | medium | git-log-grep | best-effort | 0.4 | 0.2222222222222222 |
| KLC-063 | ok | medium | git-log-grep | best-effort | 0.4 | 0.5 |
| KLC-064 | ok | medium | git-log-grep | best-effort | 0.2 | 0.1111111111111111 |
| KLC-065 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-066 | ok | medium | git-log-grep | best-effort | 0.4 | 0.0784313725490196 |
| KLC-067 | ok | high | git-log-grep | best-effort | 0.2 | 0.11764705882352941 |
| KLC-068 | ok | medium | git-log-grep | best-effort | 0.2 | 0.04 |
| KLC-069 | ok | medium | git-log-grep | best-effort | 0.2 | 0.16666666666666666 |
| KLC-070 | ok | medium | git-log-grep | best-effort | 0.4 | 0.043478260869565216 |
| KLC-071 | ok | medium | git-log-grep | best-effort | 0.0 | 0.030303030303030304 |
| KLC-072 | ok | medium | git-log-grep | best-effort | 0.2 | 0.06666666666666667 |
| KLC-073 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-074 | ok | medium | git-log-grep | best-effort | 0.2 | 0.09523809523809523 |
| KLC-075 | ok | medium | git-log-grep | best-effort | 0.0 | 0.05263157894736842 |
| KLC-076 | ok | medium | git-log-grep | best-effort | 0.4 | 0.11764705882352941 |
| KLC-077 | ok | medium | git-log-grep | best-effort | 0.8 | 0.11904761904761904 |
| KLC-078 | ok | medium | git-log-grep | best-effort | 0.6 | 0.2222222222222222 |
| KLC-079 | ok | medium | git-log-grep | best-effort | 0.2 | 0.06666666666666667 |
| KLC-080 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-081 | ok | medium | git-log-grep | best-effort | 0.2 | 0.0625 |
| KLC-082 | ok | medium | git-log-grep | best-effort | 0.2 | 0.03571428571428571 |
| KLC-083 | ok | medium | git-log-grep | best-effort | 0.6 | 0.14814814814814814 |
| KLC-084 | ok | medium | git-log-grep | best-effort | 0.2 | 0.09090909090909091 |
| KLC-085 | ok | medium | git-log-grep | best-effort | 0.4 | 0.125 |
| KLC-086 | ok | medium | git-log-grep | best-effort | 0.2 | 0.07142857142857142 |
| KLC-087 | ok | medium | git-log-grep | best-effort | 0.2 | 0.07692307692307693 |
| KLC-088 | ok | medium | git-log-grep | best-effort | 0.2 | 0.08333333333333333 |
| KLC-089 | ok | medium | git-log-grep | best-effort | 0.2 | 0.08333333333333333 |
| KLC-090 | ok | medium | git-log-grep | best-effort | 0.2 | 0.0625 |
| KLC-091 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-092 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-093 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-094 | ok | medium | git-log-grep | best-effort | 0.2 | 0.047619047619047616 |
| KLC-095 | ok | high | git-log-grep | best-effort | 0.4 | 0.16666666666666666 |
| KLC-096 | ok | medium | git-log-grep | best-effort | 0.0 | 0.045454545454545456 |
| KLC-097 | ok | medium | git-log-grep | best-effort | 0.2 | 0.0625 |
| KLC-098 | ok | high | git-log-grep | best-effort | 0.2 | 0.038461538461538464 |
| KLC-099 | ok | medium | git-log-grep | best-effort | 0.0 | 0.058823529411764705 |
| KLC-100 | ok | medium | git-log-grep | best-effort | 0.6 | 0.13793103448275862 |
| KLC-101 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-102 | ok | medium | git-log-grep | best-effort | 0.2 | 0.037037037037037035 |
| KLC-103 | ok | medium | git-log-grep | best-effort | 0.2 | 0.010416666666666666 |
| KLC-104 | ok | medium | git-log-grep | best-effort | 0.2 | 0.043478260869565216 |
| KLC-105 | ok | medium | git-log-grep | best-effort | 0.6 | 0.058823529411764705 |
| KLC-106 | ok | medium | git-log-grep | best-effort | 0.4 | 0.032520325203252036 |
| KLC-107 | ok | medium | git-log-grep | best-effort | 0.2 | 0.04411764705882353 |
| KLC-108 | ok | medium | git-log-grep | best-effort | 0.6 | 0.03333333333333333 |
| KLC-109 | ok | medium | git-log-grep | best-effort | 0.4 | 0.014814814814814815 |
| KLC-110 | ok | medium | git-log-grep | best-effort | 0.4 | 0.03896103896103896 |
| KLC-111 | ok | medium | git-log-grep | best-effort | 0.4 | 0.046875 |
| KLC-112 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-113 | ok | medium | git-log-grep | best-effort | 0.6 | 0.03333333333333333 |
| KLC-114 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-115 | ok | medium | git-log-grep | best-effort | 0.6 | 0.05 |
| KLC-116 | ok | medium | git-log-grep | best-effort | 0.4 | 0.045454545454545456 |
| KLC-117 | ok | medium | git-log-grep | best-effort | 0.8 | 0.07352941176470588 |
| KLC-118 | ok | medium | git-log-grep | best-effort | 0.8 | 0.07142857142857142 |
| KLC-119 | ok | medium | git-log-grep | best-effort | 0.4 | 0.036036036036036036 |
| KLC-120 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-121 | ok | medium | git-log-grep | best-effort | 0.2 | 0.02666666666666667 |
| KLC-122 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-123 | ok | medium | git-log-grep | best-effort | 0.6 | 0.04918032786885246 |
| KLC-124 | ok | medium | git-log-grep | best-effort | 0.2 | 0.047619047619047616 |
| KLC-125 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |
| KLC-126 | ok | medium | git-log-grep | best-effort | 0.2 | 0.025 |
| KLC-127 | ok | medium | git-log-grep | best-effort | 0.0 | 0.0 |

