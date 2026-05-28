# Intake phase

## Purpose
Accept new ticket into the system and validate raw input.

## Inputs
- `raw.md` — initial ticket description (Goals/Problem or Context)
- Human runs: `klc intake`

## Outputs
- `.klc/tickets/<KEY>/meta.json` — ticket metadata
- `.klc/tickets/<KEY>/raw.md` — stored raw input
- Ticket state: `intake:ack-needed`

## Process
1. Framework generates unique KEY (e.g., KLC-006)
2. Validates raw.md has required sections
3. Creates ticket directory structure
4. Transitions to `intake:ack-needed`

## Ack options
- `--pick 1` (confirm): Advance to discovery:work
- `--pick 2` (reject): Mark ticket as rejected, do not proceed

## Common pitfalls
- Missing Goals or Problem section in raw.md → validation failure
- Ambiguous requirements → leads to rework in discovery

## Example
```bash
# Write raw.md with goals and context
klc intake
# → Creates KLC-123, transitions to intake:ack-needed
klc ack KLC-123 --pick 1
# → Advances to discovery:work
```
