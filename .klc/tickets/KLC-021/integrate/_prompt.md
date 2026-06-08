# Agent prompt — KLC-021 · integrate:work

You are working in phase **integrate**. Read the role prompt below,
then produce the outputs listed at the bottom. When you claim the
work is done, the human runs `klc ack KLC-021` (with `--pick N` if
required) to confirm.

## Integration checklist

This phase has two ticks. During `:work`:

### Tick 1 — pre-merge
- [ ] Snapshot current artefact hashes (consistency guard).
- [ ] Open the PR / merge request.
- [ ] Address any CI / reviewer blockers.

### Tick 2 — post-merge
- [ ] Record merge commit SHA in meta.json.
- [ ] Verify CI is green on main.
- [ ] Close the Jira / tracker ticket.

When both ticks are done, run `klc ack KLC-021`.

---

## Inputs you should read

_(none; this phase has no required inputs)_

---

## Outputs the ack step will verify

_(no fixed artefacts; update whatever the role prompt specifies)_

## When done

`klc ack KLC-021`
