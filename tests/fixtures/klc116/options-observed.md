---
ticket: KLC116-FIXTURE
authority: agent
---

# Design options — KLC-116 AC-16/AC-17 fixture (rewritten `observed`)

## Option A — ship the redesigned scroll container (recommended: true)

Some prose about the option this fixture stands in for.

## Decisions

> [!DECISION D-901] owner=fixture date=2026-09-17 evidence=observed
> The page scrolls, and five mechanisms are built on that.
> ```
> $ node -e "console.log(document.scrollingElement.scrollTop)"
> 3856.67
> ```
