"""epic_plan — the KLC-079 skill-front's pre-create PLAN-SET validator + CLI seam.

This is deliberately NOT the runtime dependency resolver, and — since KLC-077
merged — it is NOT its own edge grammar either. The single source of the
`<KEY>@<point>[:cond]#<phase>` grammar and the point/condition vocabulary is
`core/skills/epic_deps.py` (KLC-077): `epic_deps.parse_edge` parses one edge and
enforces the vocab + self-reference rejection. This module REUSES it, so the
skill can never drift from the real `--blocked-by` flag.

What is genuinely KLC-079's and lives here: validation over the whole PLANNED set
BEFORE any ticket exists — dependency cycles and dangling / non-member upstreams.
That is a different moment from KLC-078's `board --epic`, which validates the
LIVE graph after tickets exist. Both are needed: this one stops a bad epic from
ever being created; the view catches drift on a running epic. Per the shared
contract (docs/20260724_epic_feature_impl_plan.md), neither can run at
single-edge write time because no single write sees the whole graph.

The `klc intake` boundary sits behind an injected seam (`intake_runner`) so the
skill's create step is unit-testable without shelling out to the real CLI.
"""
from __future__ import annotations

from dataclasses import dataclass

import epic_deps  # KLC-077 — the single edge grammar + vocab (parse_edge)


class EpicPlanError(ValueError):
    """The planned set failed validation; carries the list of problems.

    Raised by `create_epic` so the caller (the skill) can surface every problem
    at once and — critically — guarantees no `klc intake` ran (validate before
    create).
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class PlannedTicket:
    """One ticket in the planned set: key, its per-ticket description, and its
    raw `--blocked-by` edge strings.

    `description` is the ticket's rationale that the skill already gathers in
    planning step 3. It is REQUIRED because `klc intake` hard-fails without a
    description (rc 2, before any write) — a description-less ticket would create
    nothing and leave a partial epic. Edges are kept as raw strings (exactly what
    the skill passes to `--blocked-by`) so validation checks the very bytes that
    reach the CLI, parsing them through the same `epic_deps.parse_edge` the CLI
    uses.
    """

    key: str
    description: str
    blocked_by: tuple[str, ...] = ()


def _default_known_phases() -> set[str]:
    """The real downstream-phase id set, from config/phases.yml (KLC-077 intake
    validates `--blocked-by` phases against exactly this). Imported lazily so the
    validator stays unit-testable via the `known_phases` seam."""
    import phases

    return {p.id for p in phases.load_phases().ordered}


# ---------------------------------------------------------------------------
# Whole-set validation (cycles + dangling), run BEFORE any create
# ---------------------------------------------------------------------------
def validate_plan(
    planned: list[PlannedTicket],
    *,
    root: str | None = None,
    ticket_exists=None,
    known_phases=None,
) -> list[str]:
    """Validate the whole planned set. Return a list of problems (empty = ok).

    Checks, in order:
      1. every ticket has a non-empty description (`klc intake` requires one —
         an empty one would hard-fail create and leave a partial epic);
      2. every edge string parses via `epic_deps.parse_edge` — grammar, point /
         condition vocabulary, and self-reference (a 1-node cycle) are all
         enforced there, NOT re-implemented here;
      3. every edge's downstream `phase` is a real phase (in `known_phases` /
         config/phases.yml). `epic_deps.parse_edge` deliberately does NOT check
         the phase; the intake CLI does — so we mirror that check here, BEFORE
         create, or a bad `#phase` would only fail at the intake call and leave
         earlier tickets already created (a partial epic);
      4. root, if given, is a member of the planned set (it carries epic.md);
      5. no dangling edge — every `on` is a member OR an existing ticket
         (`ticket_exists(key)` seam; absent = only members count);
      6. no multi-node dependency cycle among members (mutual blocked_by → nobody
         can start). 1-node self-cycles are already rejected at step 2.

    `ticket_exists` and `known_phases` are the injectable seams (a `key -> bool`
    callable and a set of valid phase ids). In tests they are stubs; in the skill
    `known_phases` defaults to the real config/phases.yml set and `ticket_exists`
    wraps a real ticket lookup.
    """
    problems: list[str] = []
    member_keys = {t.key for t in planned}

    if not planned:
        problems.append("planned set is empty")
        return problems

    kp = set(known_phases) if known_phases is not None else _default_known_phases()

    # Duplicate member keys are an authoring error.
    seen: set[str] = set()
    for t in planned:
        if t.key in seen:
            problems.append(f"duplicate ticket {t.key!r} in planned set")
        seen.add(t.key)
        # 1. description is required by `klc intake`.
        if not (t.description or "").strip():
            problems.append(
                f"{t.key}: empty description (klc intake requires one — "
                f"use the ticket's planning rationale)"
            )

    if root is not None and root not in member_keys:
        problems.append(
            f"root {root!r} is not a member of the planned set "
            f"(the root ticket carries epic.md and must be in the set)"
        )

    # 2/3. parse edges via KLC-077's parser; check the downstream phase; build the
    #    member->member dependency adjacency for cycle detection.
    #    adjacency[d] = set of upstream member keys d depends on (d.blocked_by.on)
    adjacency: dict[str, set[str]] = {t.key: set() for t in planned}
    parsed_ok = True
    for t in planned:
        for raw in t.blocked_by:
            try:
                edge = epic_deps.parse_edge(raw, self_key=t.key)
            except ValueError as exc:
                problems.append(f"{t.key}: {exc}")
                parsed_ok = False
                continue
            # 3. downstream-phase check (intake enforces this; epic_deps does not).
            if edge["phase"] not in kp:
                problems.append(
                    f"{t.key}: unknown downstream phase {edge['phase']!r} in edge "
                    f"{raw!r} (not in config/phases.yml)"
                )
            on = edge["on"]
            # 5. dangling check.
            if on not in member_keys:
                exists = bool(ticket_exists(on)) if ticket_exists else False
                if not exists:
                    problems.append(
                        f"{t.key}: dangling edge — upstream {on!r} is not a "
                        f"member of the epic and is not an existing ticket"
                    )
            else:
                adjacency[t.key].add(on)

    # 4. cycle detection (only meaningful if edges parsed into the graph).
    if parsed_ok:
        cycle = _find_cycle(adjacency)
        if cycle:
            problems.append("dependency cycle detected: " + " -> ".join(cycle))

    return problems


def _find_cycle(adjacency: dict[str, set[str]]) -> list[str] | None:
    """Return one cycle as a node list (closed: first == last), or None.

    `adjacency[d]` holds the upstreams `d` depends on; a cycle in this
    depends-on graph means a set of tickets that can never start.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in adjacency}
    stack: list[str] = []

    def dfs(node: str) -> list[str] | None:
        color[node] = GRAY
        stack.append(node)
        for nxt in adjacency.get(node, ()):  # nxt is an upstream this node needs
            if nxt not in color:
                # upstream outside the graph (dangling) — not a cycle concern here
                continue
            if color[nxt] == GRAY:
                # back edge -> cycle from nxt .. node .. nxt
                idx = stack.index(nxt)
                return stack[idx:] + [nxt]
            if color[nxt] == WHITE:
                found = dfs(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in adjacency:
        if color[node] == WHITE:
            found = dfs(node)
            if found:
                return found
    return None


# ---------------------------------------------------------------------------
# Create step — the CLI seam
# ---------------------------------------------------------------------------
def build_intake_argv(ticket: PlannedTicket, root: str) -> list[str]:
    """Build the `klc intake` argument list for one planned ticket.

    Shape: `<KEY> --epic <ROOT> [--blocked-by <edge> ...] <description>`. The
    description is the FINAL positional — `klc intake` requires a description and
    rejects the argv (rc 2, no write) without one, so it is never omitted.
    Repeatable `--blocked-by` matches the KLC-077 flag (see core/phases/intake.py).
    """
    argv = [ticket.key, "--epic", root]
    for raw in ticket.blocked_by:
        argv += ["--blocked-by", raw]
    argv.append(ticket.description)
    return argv


def create_epic(
    root: str,
    planned: list[PlannedTicket],
    *,
    intake_runner,
    ticket_exists=None,
    known_phases=None,
) -> list:
    """Validate the whole set, THEN create every ticket via `intake_runner`.

    `intake_runner(argv: list[str]) -> Any` is the injected seam that actually
    runs `klc intake …` (real CLI in the skill; a stub in tests).

    Contract — validate before create: if `validate_plan` reports ANY problem,
    this raises `EpicPlanError` and `intake_runner` is NEVER called, so no
    partial epic is written. Only a clean set proceeds to creation.
    """
    problems = validate_plan(
        planned, root=root, ticket_exists=ticket_exists, known_phases=known_phases
    )
    if problems:
        raise EpicPlanError(problems)

    results = []
    for ticket in planned:
        results.append(intake_runner(build_intake_argv(ticket, root)))
    return results
