## Verdict contract — the two output classes

Your verdict has exactly two classes. Keep them strictly apart; when in doubt, elevate.

- **`findings[]` — OBJECTIVE, you decide.** An issue you can anchor and adjudicate.
  Each finding carries the `findings.Finding` fields
  `rule_name · severity · file · line · title · body · fix`, with `severity` one of
  CRITICAL, HIGH, MEDIUM, LOW, INFO and `rule_name` one value of YOUR closed list below.
- **`decisions_to_confirm[]` — SUBJECTIVE, the HUMAN decides.** A call with no anchor,
  settled only by whoever owns the intent. You NEVER adjudicate one: you elevate it.
  Each item leads with a non-empty `recommended` answer (state the question, then the
  answer you would pick and why). You are advising; the human resolves it at the ack
  decision gate.

If you are tempted to put a judgment call in `findings[]`, stop: if reasonable people
could disagree on the answer, it is a `decisions_to_confirm[]` item, not a finding.

Your verdict file may open with brief narrative for humans, but it MUST END with
exactly one fenced ```json block carrying both classes. The plumbing consumes that
LAST block and ignores the prose above it.
