"""The grid repository: a grid survives the round trip through the database unchanged,
and concurrent writers cannot silently overwrite each other."""

import asyncio
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.repositories import grids
from gridwise_api.tenancy import tenant_transaction
from gridwise_grid_engine import GridModel, grid_hash
from gridwise_grid_engine.reference_grids import cigre_mv
from tests.support.grids import GRID_TABLES, SAMPLE_COORDINATES, plain_grid, sample_grid

pytestmark = pytest.mark.integration


@pytest.fixture
def organization_id(tenants: dict[str, uuid.UUID]) -> uuid.UUID:
    return tenants["alpha"]


@pytest.mark.parametrize(
    ("model", "coordinates"),
    [
        (sample_grid(), SAMPLE_COORDINATES),
        (plain_grid("Plain feeder (synthetic)"), None),
        (cigre_mv.cigre_mv_with_der(), cigre_mv.BUS_DIAGRAM_COORDINATES),
    ],
    ids=["every-option", "no-options", "cigre-mv"],
)
async def test_a_grid_is_stored_and_read_back_unchanged(
    organization_id: uuid.UUID,
    app_async_engine: AsyncEngine,
    model: GridModel,
    coordinates: dict[str, tuple[float, float]] | None,
) -> None:
    async with tenant_transaction(app_async_engine, organization_id) as session:
        created = await grids.create_grid(
            session,
            model,
            description="A test grid.",
            diagram_coordinates=coordinates,
        )

    async with tenant_transaction(app_async_engine, organization_id) as session:
        stored = await grids.load_grid(session, created.id)

    assert stored is not None
    # Element order is not part of a grid's identity; the hash is the comparison.
    assert grid_hash(stored.model) == grid_hash(model)
    assert stored.record.topology_hash == grid_hash(model)
    assert stored.diagram_coordinates == dict(coordinates or {})
    assert stored.record == created
    assert (stored.record.version, stored.record.data_origin) == (1, "synthetic")
    assert stored.record.description == "A test grid."
    assert stored.record.organization_id == organization_id


async def test_every_value_survives_exactly(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    """Not just the hash: the rebuilt elements equal the originals, field by field."""
    model = sample_grid()
    async with tenant_transaction(app_async_engine, organization_id) as session:
        created = await grids.create_grid(session, model)
        stored = await grids.load_grid(session, created.id)
    assert stored is not None

    def by_id(items: tuple[object, ...]) -> dict[str, object]:
        return {item.id: item for item in items}  # type: ignore[attr-defined]

    for group in (
        "buses",
        "lines",
        "transformers",
        "loads",
        "generators",
        "external_grids",
        "switches",
    ):
        assert by_id(getattr(stored.model, group)) == by_id(getattr(model, group)), group
    assert stored.model.frequency_hz == model.frequency_hz
    assert stored.model.name == model.name


async def test_reading_is_deterministic(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    async with tenant_transaction(app_async_engine, organization_id) as session:
        created = await grids.create_grid(session, cigre_mv.cigre_mv_with_der())
    loaded = []
    for _ in range(2):
        async with tenant_transaction(app_async_engine, organization_id) as session:
            loaded.append(await grids.load_grid(session, created.id))
    assert loaded[0] == loaded[1]  # same element order every time


async def test_a_missing_grid_is_none_not_an_error(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    async with tenant_transaction(app_async_engine, organization_id) as session:
        assert await grids.get_grid(session, uuid.uuid4()) is None
        assert await grids.load_grid(session, uuid.uuid4()) is None
        assert await grids.delete_grid(session, uuid.uuid4()) is False


async def test_creation_is_atomic(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    """A topology the database refuses leaves no grid and no elements behind."""
    model = sample_grid()
    broken = replace(
        model,
        lines=(replace(model.lines[0], length_km=0.0), model.lines[1]),
    )
    with pytest.raises(Exception, match="length_positive"):
        async with tenant_transaction(app_async_engine, organization_id) as session:
            await grids.create_grid(session, broken)

    with owner_engine.connect() as connection:
        for table in GRID_TABLES:
            count = connection.execute(text(f"SELECT count(*) FROM grid.{table}")).scalar_one()  # noqa: S608
            assert count == 0, table


async def test_deleting_a_grid_removes_all_of_its_elements_and_nothing_else(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    async with tenant_transaction(app_async_engine, organization_id) as session:
        doomed = await grids.create_grid(session, sample_grid("Doomed (synthetic)"))
        kept = await grids.create_grid(session, sample_grid("Kept (synthetic)"))

    async with tenant_transaction(app_async_engine, organization_id) as session:
        assert await grids.delete_grid(session, doomed.id) is True

    with owner_engine.connect() as connection:
        for table in GRID_TABLES[1:]:
            remaining = connection.execute(
                text(f"SELECT DISTINCT grid_id FROM grid.{table}")  # noqa: S608
            ).scalars()
            assert list(remaining) == [kept.id], table
    async with tenant_transaction(app_async_engine, organization_id) as session:
        assert await grids.get_grid(session, doomed.id) is None
        survivor = await grids.load_grid(session, kept.id)
    assert survivor is not None
    assert grid_hash(survivor.model) == grid_hash(sample_grid("Kept (synthetic)"))


async def test_chosen_ids_are_used(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    grid_id = uuid.UUID("11111111-1111-4111-8111-111111111111")

    def element_id(table: str, key: str) -> uuid.UUID:
        return uuid.uuid5(grid_id, f"{table}:{key}")

    async with tenant_transaction(app_async_engine, organization_id) as session:
        created = await grids.create_grid(
            session, sample_grid(), grid_id=grid_id, element_id=element_id
        )
    assert created.id == grid_id
    with owner_engine.connect() as connection:
        rows = connection.execute(text("SELECT key, id FROM grid.buses")).all()
        target = connection.execute(
            text("SELECT line_id FROM grid.switches WHERE key = 's-bc'")
        ).scalar_one()
    assert {row.key: row.id for row in rows} == {
        key: element_id("buses", key) for key in ("hv", "a", "b", "c", "d")
    }
    assert target == element_id("lines", "bc")


# --- optimistic concurrency (decision 0007, D5) -----------------------------------------


async def test_claiming_the_current_version_increments_it(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    async with tenant_transaction(app_async_engine, organization_id) as session:
        created = await grids.create_grid(session, sample_grid())
    async with tenant_transaction(app_async_engine, organization_id) as session:
        assert await grids.claim_version(session, created.id, 1) == 2
    async with tenant_transaction(app_async_engine, organization_id) as session:
        assert await grids.claim_version(session, created.id, 2) == 3
        record = await grids.get_grid(session, created.id)
    assert record is not None
    assert record.version == 3
    assert record.updated_at > created.updated_at


@pytest.mark.parametrize("stale", [0, 2, 99, -1])
async def test_a_stale_version_is_a_conflict_and_changes_nothing(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine, stale: int
) -> None:
    async with tenant_transaction(app_async_engine, organization_id) as session:
        created = await grids.create_grid(session, sample_grid())

    with pytest.raises(grids.GridVersionConflictError):
        async with tenant_transaction(app_async_engine, organization_id) as session:
            await grids.claim_version(session, created.id, stale)

    async with tenant_transaction(app_async_engine, organization_id) as session:
        record = await grids.get_grid(session, created.id)
    assert record is not None
    assert record.version == 1


async def test_a_claim_is_undone_when_its_transaction_fails(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    async with tenant_transaction(app_async_engine, organization_id) as session:
        created = await grids.create_grid(session, sample_grid())

    async def claim_then_fail() -> None:
        async with tenant_transaction(app_async_engine, organization_id) as session:
            await grids.claim_version(session, created.id, 1)
            raise RuntimeError("write failed")

    with pytest.raises(RuntimeError, match="write failed"):
        await claim_then_fail()

    async with tenant_transaction(app_async_engine, organization_id) as session:
        assert await grids.claim_version(session, created.id, 1) == 2  # still at 1 before this


async def test_of_two_concurrent_writers_exactly_one_wins(
    organization_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    """Both read version 1 and both try to write. The loser waits for the winner's row
    lock, then sees the version has moved on. Neither overwrites the other."""
    async with tenant_transaction(app_async_engine, organization_id) as session:
        created = await grids.create_grid(session, sample_grid())
    both_ready = asyncio.Barrier(2)

    async def write(label: str) -> str:
        try:
            async with tenant_transaction(app_async_engine, organization_id) as session:
                await session.execute(text("SELECT 1"))  # the transaction is open
                await both_ready.wait()
                await grids.claim_version(session, created.id, 1)
                await session.execute(
                    text("UPDATE grid.grids SET description = :label WHERE id = :id"),
                    {"label": label, "id": created.id},
                )
                await asyncio.sleep(0.05)  # hold the lock while the other one arrives
            return "won"
        except grids.GridVersionConflictError:
            return "conflict"

    outcomes = await asyncio.gather(write("first"), write("second"))
    assert sorted(outcomes) == ["conflict", "won"]

    async with tenant_transaction(app_async_engine, organization_id) as session:
        record = await grids.get_grid(session, created.id)
    assert record is not None
    assert record.version == 2
    winner = "first" if outcomes[0] == "won" else "second"
    assert record.description == winner
