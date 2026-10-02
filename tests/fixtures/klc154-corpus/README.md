# tests/fixtures/klc154-corpus — frozen migration corpus (KLC-154)

A flat (D-008), self-authored, redaction-clean sample covering the five old
shapes of `spec.md`'s Data shapes section and the three Q-103 legacy cases.
Every file is named `KEY__relpath` (`/` in relpath encoded as `--`); every
ticket key is in the dedicated synthetic range `KLC-2001`..`KLC-2030`, chosen so
nothing here is a real project ticket. `_klc154_support.materialize_corpus`
expands each flat file back into a scratch `tickets/<KEY>/<relpath>` tree with a
synthetic `meta.json` per ticket.

| file | shape | derivation |
|---|---|---|
| `KLC-2001__spec-review-findings.json` | independent JSON list (shape 1) | self-authored, matches the spec reviewer's real vocabulary |
| `KLC-2001__spec-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above, same findings |
| `KLC-2002__spec-review-findings.json` | independent JSON list (shape 1) | Q-103: category 'scope-creep' is out of the spec vocabulary |
| `KLC-2002__spec-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2020__spec-review-findings.json` | independent JSON list (shape 1) | padding pair |
| `KLC-2020__spec-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2023__spec-review-findings.json` | independent JSON list (shape 1) | padding pair |
| `KLC-2023__spec-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2029__spec-review-findings.json` | independent JSON list (shape 1) | JSON-only, no .md |
| `KLC-2003__test-plan-review-findings.json` | independent JSON list (shape 1) | self-authored |
| `KLC-2003__test-plan-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2004__test-plan-review-findings.json` | independent JSON list (shape 1) | self-authored |
| `KLC-2004__test-plan-review.md` | old-shape .md verdict (shape 5) | Q-103: decision uses 'recommendation' instead of 'recommended' |
| `KLC-2024__test-plan-review-findings.json` | independent JSON list (shape 1) | padding pair |
| `KLC-2024__test-plan-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2018__test-plan-review.md` | old-shape .md verdict, no JSON (shape 5) | md-only ticket (D-106) |
| `KLC-2030__test-plan-review-findings.json` | independent JSON list (shape 1) | JSON-only, no .md |
| `KLC-2005__impl-plan-review-findings.json` | independent JSON list (shape 1) | self-authored |
| `KLC-2005__impl-plan-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2006__impl-plan-review-findings.json` | independent JSON list (shape 1) | JSON-only, no .md |
| `KLC-2025__impl-plan-review-findings.json` | independent JSON list (shape 1) | padding pair |
| `KLC-2025__impl-plan-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2019__impl-plan-review.md` | old-shape .md verdict, no JSON (shape 5) | md-only ticket (D-106) |
| `KLC-2007__drift-review-findings.json` | independent JSON list (shape 1) | self-authored |
| `KLC-2007__drift-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2008__drift-review.md` | old-shape .md verdict, no JSON (shape 5) | md-only ticket (E-7 straggler) |
| `KLC-2021__drift-review-findings.json` | independent JSON list (shape 1) | padding pair |
| `KLC-2021__drift-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2026__drift-review-findings.json` | independent JSON list (shape 1) | padding pair |
| `KLC-2026__drift-review.md` | old-shape .md verdict (shape 5) | paired with the JSON above |
| `KLC-2009__review--code-review-findings.json` | in-client list, integer line (shape 2) | self-authored, post-KLC-127 straggler style |
| `KLC-2010__review--code-review-findings.json` | in-client list, integer line (shape 2) | Q-103: one record carries line: 0 (becomes null) |
| `KLC-2011__review--external-review-findings.json` | in-client list, line: null (shape 3) | self-authored |
| `KLC-2012__review--external-review-findings.json` | in-client list, integer line (shape 2) | self-authored |
| `KLC-2013__review--code-review-findings.json` | in-client list, line: null (shape 3) | self-authored |
| `KLC-2014__review--external-review-findings.json` | in-client list, line: null (shape 3) | derived (A-101): the third line:null in-client instance |
| `KLC-2022__review--code-review-findings.json` | in-client list, integer line (shape 2) | padding |
| `KLC-2027__review--code-review-findings.json` | in-client list, integer line (shape 2) | padding |
| `KLC-2028__review--external-review-findings.json` | in-client list, integer line (shape 2) | padding |
| `KLC-2015__spec-review-findings.json` | empty findings list (shape 4) | round-trips trivially; paired below with a real change |
| `KLC-2015__test-plan-review-findings.json` | independent JSON list (shape 1) | gives KLC-2015 a real change to migrate |
| `KLC-2016__review--code-review-findings.json` | empty findings list (shape 4) | round-trips trivially; paired below with a real change |
| `KLC-2016__spec-review-findings.json` | independent JSON list (shape 1) | gives KLC-2016 a real change to migrate |
| `KLC-2017__review--external-review-findings.json` | empty findings list (shape 4) | round-trips trivially; paired below with a real change |
| `KLC-2017__impl-plan-review-findings.json` | independent JSON list (shape 1) | gives KLC-2017 a real change to migrate |
