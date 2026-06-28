## Approach options
- Option A: Inline `klc remind` in existing `gate.py` hook — extend the single UserPromptSubmit hook to emit a reminder line when the holder check fires; avoids a second hook process but couples gate and remind logic in one file.
- Option B: Separate `remind.py` script registered as a second UserPromptSubmit hook — `klc remind` is a standalone script/phase that reads meta.json, checks `phase_completion.can_complete`, compares holder identity; keeps gate and remind decoupled but adds a new hook entry and a new CLI verb.
- Option C: `klc remind` as a CLI verb only, no hook — user calls it manually or from their own shell hooks; no automated delivery, requires user discipline.

Picked: Option B — a standalone `remind.py` script keeps gate and remind concerns separate, satisfies the `klc remind` CLI contract the ticket specifies, is independently testable, and integrates cleanly with the existing hooks.json pattern. Option A conflates two distinct concerns; Option C removes the automated delivery the ticket explicitly requires.
