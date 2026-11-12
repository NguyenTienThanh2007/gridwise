"""Energisation: which buses can an external grid reach?

A plain graph search over in-service elements, independent of any solver. The engine uses
it to decide which results must exist and which must be absent, and cross-checks the
solver's output against it.
"""

from collections import defaultdict, deque

from gridwise_grid_engine.model import GridModel, Line


def in_service_bus_ids(grid: GridModel) -> frozenset[str]:
    return frozenset(bus.id for bus in grid.buses if bus.in_service)


def line_is_connected(line: Line, in_service_buses: frozenset[str]) -> bool:
    """A line carries current only if it and both of its end buses are in service.

    Taking a bus out of service takes every element attached to it out of service. In
    particular an in-service line is NOT left energised from its other end: the engine does
    not model open-ended lines, and saying so here keeps the solver from doing it silently.
    """
    return (
        line.in_service
        and line.from_bus_id in in_service_buses
        and line.to_bus_id in in_service_buses
    )


def energized_bus_ids(grid: GridModel) -> frozenset[str]:
    """Ids of in-service buses connected to an in-service external grid."""
    in_service = in_service_bus_ids(grid)

    neighbours: defaultdict[str, set[str]] = defaultdict(set)
    for line in grid.lines:
        if line_is_connected(line, in_service):
            neighbours[line.from_bus_id].add(line.to_bus_id)
            neighbours[line.to_bus_id].add(line.from_bus_id)

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
    return frozenset(reached)
