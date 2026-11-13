"""HTTP schemas <-> engine model, without a database or an app."""

from dataclasses import replace

from gridwise_api.api.schemas.grid_mapping import model_from_topology, topology_from_model
from gridwise_api.api.schemas.grids import TopologySchema
from gridwise_grid_engine import grid_hash
from gridwise_grid_engine.reference_grids import cigre_mv
from tests.support.grids import SAMPLE_COORDINATES, plain_grid, sample_grid


def test_a_model_survives_the_round_trip_through_the_http_schema() -> None:
    for model, coordinates in (
        (sample_grid(), SAMPLE_COORDINATES),
        (plain_grid("plain"), {}),
        (cigre_mv.cigre_mv_with_der(), cigre_mv.BUS_DIAGRAM_COORDINATES),
    ):
        document = topology_from_model(model, coordinates).model_dump(mode="json")
        parsed = TopologySchema.model_validate(document)  # as a request would be
        rebuilt, rebuilt_coordinates = model_from_topology(model.name, parsed)
        assert rebuilt == model
        assert rebuilt_coordinates == dict(coordinates)


def test_the_name_comes_from_the_caller_not_the_document() -> None:
    document = topology_from_model(sample_grid(), {})
    model, _ = model_from_topology("Another name", document)
    assert grid_hash(model) == grid_hash(replace(sample_grid(), name="Another name"))


def test_the_document_carries_keys_not_row_ids() -> None:
    document = topology_from_model(sample_grid(), {}).model_dump()
    switch = next(item for item in document["switches"] if item["key"] == "s-bc")
    assert switch == {
        "key": "s-bc",
        "name": "S bc",
        "bus_key": "c",
        "element_type": "line",
        "element_key": "bc",
        "closed": False,
        "kind": "load_break_switch",
    }
    assert all(
        "id" not in item for group in document.values() if isinstance(group, list) for item in group
    )
