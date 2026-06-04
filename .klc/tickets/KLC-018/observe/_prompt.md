# Agent prompt — KLC-018 · observe:work

You are working in phase **observe**. Read the role prompt below,
then produce the outputs listed at the bottom. When you claim the
work is done, the human runs `klc ack KLC-018` (with `--pick N` if
required) to confirm.

## Observation checklist

No agent runs in this phase. The task is to monitor the merged change for regressions and close the loop with `klc ack`.

Suggested watchlist (customise per ticket):

- [ ] Error-rate dashboard for affected service(s)
- [ ] p95 / p99 latency for the touched endpoints
- [ ] Relevant SLO budget burn rate
- [ ] Feature flag rollout percentage (if applicable)
- [ ] User-report channels (support, feedback) for regressions

When the observation window closes, run `klc ack KLC-018 --pick 1` (clean), `--pick 2` (regression, auto-reopens build), or `--pick 3` (rollback).

---

## Inputs you should read

_(none; this phase has no required inputs)_

---

## Outputs the ack step will verify

_(no fixed artefacts; update whatever the role prompt specifies)_

## When done

`klc ack KLC-018 --pick <N>`, where N is:

  - `1` = clean
  - `2` = regression
  - `3` = rollback
