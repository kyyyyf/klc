# klc happy path

The shortest walk from `klc intake` to `archived` for a clean **S-track** ticket
(`risk_tags: []`, no rework / regression / budget overrun). Copy the commands,
swap in your `<KEY>`. For the full contract see [`docs/process.md`](process.md).

**Key rule:** every forward `klc ack --pick 1` here *also advances* to the next
phase's `:work` (the pick's `goto` is `next`, so ack advances immediately). So the
happy path is **ack-only** — you never run `klc next`. Running `klc next` from a
`:work` state errors ("finish the work and run `klc ack`").

## The flow

```text
klc intake <KEY> "one-line description"   # → intake:ack-needed  (writes raw.md + meta.json)
klc ack    <KEY> --pick 1                 # confirm-route → discovery-lite:work (prints a prompt card)
   # agent writes: spec.md, options-lite.md (>=2 approaches + a recorded "Picked:"), impl-plan.md
klc ack    <KEY> --pick 1                 # approve → build:work
   # on a feature branch (per CLAUDE.md): write code + build-log.md (a "## Evidence" fenced block).
   # Commit the failing test BEFORE the fix for each impl-plan step — the build ack enforces
   # red-before-green commit order from git history, so a valid build-log alone is not enough.
klc ack    <KEY> --pick 1                 # approve → review:work
   # agent writes review-report.md
klc ack    <KEY> --pick 1                 # approve → integrate:work ; merge the feature branch
klc ack    <KEY>                          # merged → archived  (integrate pick_required=false;
                                          #   observe + learn are condition-skipped for a clean S)
```

`observe` and `learn` are condition-gated in `config/phases.yml`: `observe` runs only for
risk tags (user-facing / data / security / migration) and `learn` only for M/L tracks or
failure signals (rework / regression / budget overrun). A clean S ticket satisfies neither,
so the single `klc ack` that confirms `integrate` skips both and lands on `archived` —
there is no separate `klc next` and no `learn` pick.

## Step → artifact → advancing command

| Step           | Artifact(s) produced                        | Advancing command       |
|----------------|---------------------------------------------|-------------------------|
| intake         | `raw.md`, `meta.json`                        | `klc ack --pick 1`      |
| discovery-lite | `spec.md`, `options-lite.md`, `impl-plan.md` | `klc ack --pick 1`     |
| build          | code + `build-log.md` (## Evidence block)   | `klc ack --pick 1`      |
| review         | `review-report.md`                           | `klc ack --pick 1`     |
| integrate      | merge commit (checklist, no artifact file)  | `klc ack` (no pick)     |

## Shortcuts & checks

- `klc ship <KEY> --pick N` is shorthand for `klc ack` (ack already advances and renders the next card).
- To re-read the current card: `cat .klc/tickets/<KEY>/<phase>/_prompt.md` (or `klc status <KEY>`).
- discovery-lite ack gate: `spec.md` + `options-lite.md` + `impl-plan.md`. (`test-plan.md` is also
  listed in phases.yml `outputs` and is good practice, but it is not what the ack gate blocks on.)
- Verify before acking build: `python3 -m pytest tests/ -q --ignore=tests/fixtures` (or `klc doctor --tests`).
