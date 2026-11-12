"""Energisation: what can an external grid reach?

A plain graph search over in-service elements and closed switches, independent of any
solver. The engine uses it to decide which results must exist and which must be absent,
and cross-checks the solver's output against it.

Rules, in order:

1. Taking a bus out of service takes every element attached to it out of service. A line
   or transformer with an out-of-service bus at either end is disconnected entirely.
2. An open switch at one end of a line or transformer detaches that end only. The element
   stays energised from its other end if that end is attached to an energised bus: an
   open-ended line draws its charging current, a transformer its no-load current.
3. Power passes through a line or transformer only if both ends are attached, and through
   a bus-to-bus switch only if it is closed.
4. Only an in-service external grid energises a network. Generators do not: a part of the
   network without an external grid is de-energised, whatever generation it contains.
"""

from collections import defaultdict, deque
from dataclasses import dataclass

from gridwise_grid_engine.model import GridModel, Line, Transformer


def in_service_bus_ids(grid: GridModel) -> frozenset[str]:
    return frozenset(bus.id for bus in grid.buses if bus.in_service)


def line_is_connected(line: Line, in_service_buses: frozenset[str]) -> bool:
    """Rule 1 for a line: it and both of its end buses are in service."""
    return (
        line.in_service
        and line.from_bus_id in in_service_buses
        and line.to_bus_id in in_service_buses
    )


def transformer_is_connected(transformer: Transformer, in_service_buses: frozenset[str]) -> bool:
    """Rule 1 for a transformer: it and both of its buses are in service."""
    return (
        transformer.in_service
        and transformer.hv_bus_id in in_service_buses
        and transformer.lv_bus_id in in_service_buses
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Energization:
    """Which buses, lines and transformers carry voltage."""

    bus_ids: frozenset[str]
    line_ids: frozenset[str]
    transformer_ids: frozenset[str]


def analyze_energization(grid: GridModel) -> Energization:
    in_service = in_service_bus_ids(grid)

    # (element type, element id, bus id) of every end detached by an open switch.
    open_ends = {
        (switch.element_type, switch.element_id, switch.bus_id)
        for switch in grid.switches
        if not switch.closed and switch.element_type in ("line", "transformer")
    }

    def attached_ends(kind: str, element_id: str, ends: tuple[str, str]) -> tuple[str, ...]:
        return tuple(bus_id for bus_id in ends if (kind, element_id, bus_id) not in open_ends)

    neighbours: defaultdict[str, set[str]] = defaultdict(set)

    def join(first: str, second: str) -> None:
        neighbours[first].add(second)
        neighbours[second].add(first)

    # Ends of each connected branch that are attached to their bus.
    line_ends: dict[str, tuple[str, ...]] = {}
    for line in grid.lines:
        if line_is_connected(line, in_service):
            ends = attached_ends("line", line.id, (line.from_bus_id, line.to_bus_id))
            line_ends[line.id] = ends
            if len(ends) == 2:
                join(*ends)
    transformer_ends: dict[str, tuple[str, ...]] = {}
    for transformer in grid.transformers:
        if transformer_is_connected(transformer, in_service):
            ends = attached_ends(
                "transformer", transformer.id, (transformer.hv_bus_id, transformer.lv_bus_id)
            )
            transformer_ends[transformer.id] = ends
            if len(ends) == 2:
                join(*ends)
    for switch in grid.switches:
        if (
            switch.element_type == "bus"
            and switch.closed
            and switch.bus_id in in_service
            and switch.element_id in in_service
        ):
            join(switch.bus_id, switch.element_id)

    reached = {
        source.bus_id
        for source in grid.external_grids
        if source.in_service and source.bus_id in in_service
    }
    queue = deque(sorted(reached))
    while queue:
        for neighbour in neighbours[queue.popleft()]:
            if neighbour not in reached:
                reached.add(neighbour)
                queue.append(neighbour)

    return Energization(
        bus_ids=frozenset(reached),
        line_ids=frozenset(
            line_id for line_id, ends in line_ends.items() if any(end in reached for end in ends)
        ),
        transformer_ids=frozenset(
            transformer_id
            for transformer_id, ends in transformer_ends.items()
            if any(end in reached for end in ends)
        ),
    )


def energized_bus_ids(grid: GridModel) -> frozenset[str]:
    """Ids of in-service buses that an in-service external grid can reach."""
    return analyze_energization(grid).bus_ids
