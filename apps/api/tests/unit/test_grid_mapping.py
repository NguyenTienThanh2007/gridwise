"""Model <-> rows translation, without a database."""

import uuid

from gridwise_api.repositories.grid_mapping import (
    ELEMENT_TABLES,
    assign_ids,
    element_keys,
    model_from_rows,
    rows_from_model,
)
from gridwise_grid_engine import grid_hash
from gridwise_grid_engine.reference_grids import cigre_mv
from tests.support.grids import SAMPLE_COORDINATES, plain_grid, sample_grid

ORGANIZATION = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
GRID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _element_id(table: str, key: str) -> uuid.UUID:
    return uuid.uuid5(GRID, f"{table}:{key}")


def _rows(model: object, coordinates: object = None) -> dict[str, list[dict[str, object]]]:
    return rows_from_model(
        model,  # type: ignore[arg-type]
        organization_id=ORGANIZATION,
        grid_id=GRID,
        ids=assign_ids(model, _element_id),  # type: ignore[arg-type]
        diagram_coordinates=coordinates,  # type: ignore[arg-type]
    )


def test_a_model_survives_the_translation_to_rows_and_back() -> None:
    for model, coordinates in (
        (sample_grid(), SAMPLE_COORDINATES),
        (plain_grid("plain"), None),
        (cigre_mv.cigre_mv_with_der(), cigre_mv.BUS_DIAGRAM_COORDINATES),
    ):
        rebuilt, rebuilt_coordinates = model_from_rows(
            name=model.name, frequency_hz=model.frequency_hz, rows=_rows(model, coordinates)
        )
        assert grid_hash(rebuilt) == grid_hash(model)
        assert rebuilt_coordinates == dict(coordinates or {})


def test_every_row_carries_its_tenant_and_grid() -> None:
    rows = _rows(sample_grid())
    assert set(rows) == set(ELEMENT_TABLES)
    for table, items in rows.items():
        assert items, table
        for row in items:
            assert (row["organization_id"], row["grid_id"]) == (ORGANIZATION, GRID)
            assert row["id"] == _element_id(table, str(row["key"]))


def test_references_are_row_ids_of_the_same_grid() -> None:
    rows = _rows(sample_grid())
    bus_ids = {row["id"] for row in rows["buses"]}
    for table, columns in {
        "lines": ("from_bus_id", "to_bus_id"),
        "transformers": ("hv_bus_id", "lv_bus_id"),
        "loads": ("bus_id",),
        "generators": ("bus_id",),
        "external_grids": ("bus_id",),
        "switches": ("bus_id",),
    }.items():
        for row in rows[table]:
            for column in columns:
                assert row[column] in bus_ids, (table, column)


def test_a_switch_row_has_exactly_one_target() -> None:
    rows = {row["key"]: row for row in _rows(sample_grid())["switches"]}
    targets = ("line_id", "transformer_id", "other_bus_id")
    for row in rows.values():
        assert sum(row[column] is not None for column in targets) == 1
    assert rows["s-bc"]["line_id"] == _element_id("lines", "bc")
    assert rows["cb-t1"]["transformer_id"] == _element_id("transformers", "t1")
    assert rows["coupler"]["other_bus_id"] == _element_id("buses", "d")
    assert rows["s-bc"]["closed"] is False


def test_an_absent_tap_changer_and_absent_options_are_nulls_not_zeros() -> None:
    rows = _rows(plain_grid("plain"))
    (transformer,) = rows["transformers"]
    assert all(transformer[column] is None for column in transformer if column.startswith("tap_"))

    generators = {row["key"]: row for row in _rows(sample_grid())["generators"]}
    assert generators["pv"]["voltage_setpoint_pu"] is None
    assert generators["pv"]["min_q_mvar"] is None
    assert generators["chp"]["q_mvar"] is None
    assert generators["chp"]["rated_power_mva"] is None


def test_buses_without_coordinates_get_none() -> None:
    buses = {row["key"]: row for row in _rows(sample_grid(), SAMPLE_COORDINATES)["buses"]}
    assert (buses["a"]["diagram_x"], buses["a"]["diagram_y"]) == SAMPLE_COORDINATES["a"]
    assert (buses["d"]["diagram_x"], buses["d"]["diagram_y"]) == (None, None)


def test_coordinates_are_not_part_of_the_topology_hash() -> None:
    model = sample_grid()
    with_coordinates, _ = model_from_rows(
        name=model.name, frequency_hz=50.0, rows=_rows(model, SAMPLE_COORDINATES)
    )
    without, _ = model_from_rows(name=model.name, frequency_hz=50.0, rows=_rows(model))
    assert grid_hash(with_coordinates) == grid_hash(without)


def test_rebuilt_elements_are_ordered_by_key_whatever_the_row_order() -> None:
    model = sample_grid()
    rows = _rows(model)
    reversed_rows = {table: list(reversed(items)) for table, items in rows.items()}
    first, _ = model_from_rows(name=model.name, frequency_hz=50.0, rows=rows)
    second, _ = model_from_rows(name=model.name, frequency_hz=50.0, rows=reversed_rows)
    assert first == second
    assert [bus.id for bus in first.buses] == sorted(bus.id for bus in model.buses)


def test_ids_are_assigned_once_per_element_in_a_fixed_order() -> None:
    model = sample_grid()
    calls: list[tuple[str, str]] = []

    def record(table: str, key: str) -> uuid.UUID:
        calls.append((table, key))
        return _element_id(table, key)

    assign_ids(model, record)
    expected = [(table, key) for table, keys in element_keys(model).items() for key in keys]
    assert calls == expected
    assert len(calls) == len(set(calls)) == 16
