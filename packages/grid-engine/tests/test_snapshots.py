"""Snapshots: canonical text whose hash is the grid hash, read back exactly."""

import json
from dataclasses import replace

import pytest
from grid_factories import substation_feeder, switch, three_bus_radial, transformer_feeder, two_bus

from gridwise_grid_engine import TapChanger, grid_hash, validate_grid
from gridwise_grid_engine.reference_grids import cigre_mv
from gridwise_grid_engine.snapshots import (
    SnapshotError,
    grid_from_snapshot,
    snapshot_hash,
    snapshot_text,
)

TAP = TapChanger(
    side="lv", neutral_position=0, min_position=-9, max_position=9, step_percent=1.5, position=-3
)
GRIDS = [
    two_bus(),
    three_bus_radial(),
    transformer_feeder(tap=TAP),
    replace(substation_feeder(), switches=(switch("s", "c", "line", "bc", closed=False),)),
    cigre_mv.cigre_mv_with_der(),
]


@pytest.mark.parametrize("grid", GRIDS, ids=lambda grid: grid.name)
def test_a_snapshot_reads_back_as_the_same_grid(grid: object) -> None:
    text = snapshot_text(grid)  # type: ignore[arg-type]
    rebuilt = grid_from_snapshot(text, expected_hash=snapshot_hash(text))
    assert grid_hash(rebuilt) == grid_hash(grid)  # type: ignore[arg-type]
    assert snapshot_text(rebuilt) == text
    assert validate_grid(rebuilt) == ()


@pytest.mark.parametrize("grid", GRIDS, ids=lambda grid: grid.name)
def test_the_snapshot_hash_is_the_grid_hash(grid: object) -> None:
    assert snapshot_hash(snapshot_text(grid)) == grid_hash(grid)  # type: ignore[arg-type]


def test_tap_positions_come_back_as_integers() -> None:
    rebuilt = grid_from_snapshot(snapshot_text(transformer_feeder(tap=TAP)))
    tap = rebuilt.transformers[0].tap
    assert tap is not None
    assert all(
        type(value) is int
        for value in (tap.position, tap.neutral_position, tap.min_position, tap.max_position)
    )


def test_element_order_does_not_change_the_text() -> None:
    grid = three_bus_radial()
    shuffled = replace(grid, buses=tuple(reversed(grid.buses)), loads=tuple(reversed(grid.loads)))
    assert snapshot_text(shuffled) == snapshot_text(grid)


def test_a_snapshot_is_compact_canonical_json() -> None:
    text = snapshot_text(two_bus())
    assert json.dumps(json.loads(text), sort_keys=True, separators=(",", ":")) == text
    assert json.loads(text)["schema"] == "gridwise.grid/2"


def test_a_changed_byte_is_detected_by_the_hash() -> None:
    text = snapshot_text(two_bus())
    tampered = text.replace('"p_mw":4.0', '"p_mw":4.1')
    assert tampered != text
    with pytest.raises(SnapshotError, match="hash"):
        grid_from_snapshot(tampered, expected_hash=snapshot_hash(text))


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"schema":"gridwise.grid/1","grid":{}}',
        '{"schema":"gridwise.grid/2","grid":{"name":"x"}}',
    ],
)
def test_anything_but_a_snapshot_is_refused(text: str) -> None:
    with pytest.raises(SnapshotError):
        grid_from_snapshot(text)


def test_a_non_canonical_spelling_of_the_same_grid_is_refused() -> None:
    """Readers rely on the text being the canonical form; a re-spelled copy is not."""
    pretty = json.dumps(json.loads(snapshot_text(two_bus())), indent=2, sort_keys=True)
    with pytest.raises(SnapshotError, match="canonical"):
        grid_from_snapshot(pretty)


def test_a_fractional_tap_position_is_refused() -> None:
    document = json.loads(snapshot_text(transformer_feeder(tap=TAP)))
    document["grid"]["transformers"][0]["tap"]["position"] = 1.5
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    with pytest.raises(SnapshotError, match="integer"):
        grid_from_snapshot(text)
