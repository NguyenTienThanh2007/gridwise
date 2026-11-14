"""Reading results through the API role: checked, summarised, tenant-scoped."""

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.services.results import ResultNotAvailableError, ResultService
from gridwise_api.services.simulations import JobNotFoundError, StoredDataIntegrityError
from gridwise_grid_engine.scenarios import demand_increase, scenario_document
from tests.support.simulations import claim, fail, finish_with_real_result, service, stored_grid

pytestmark = pytest.mark.integration


@pytest.fixture
async def finished(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine, worker_engine: Engine
) -> uuid.UUID:
    grid_id = await stored_grid(app_async_engine, tenants["alpha"])
    await service(app_async_engine).submit(tenants["alpha"], grid_id)
    return finish_with_real_result(worker_engine)


async def test_a_converged_result_and_its_summary(
    finished: uuid.UUID, tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    result = await ResultService(app_async_engine).get(tenants["alpha"], finished)
    assert result.outcome == "converged"
    assert result.result_hash is not None
    assert result.document is not None
    summary = result.summary
    assert summary.converged is True
    assert summary.totals is not None
    # The sample grid: switch s-bc is open at c, so bus c and its 1 MW load are cut off,
    # and bus d is out of service.
    assert summary.totals.served_load_mw == pytest.approx(2.0)
    assert summary.totals.unserved_load_mw == pytest.approx(1.0)
    assert summary.min_bus_voltage_pu is not None
    assert summary.de_energised_buses == 2
    assert summary.unsupplied_bus_ids == ("c",)


async def test_a_result_that_did_not_converge_has_no_values(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine, worker_engine: Engine
) -> None:
    grid_id = await stored_grid(app_async_engine, tenants["alpha"])
    scenario = await service(app_async_engine).create_scenario(
        tenants["alpha"],
        name="100x",
        description="",
        document=scenario_document(demand_increase(100)),
    )
    await service(app_async_engine).submit(tenants["alpha"], grid_id, scenario_id=scenario.id)
    job = finish_with_real_result(worker_engine)
    result = await ResultService(app_async_engine).get(tenants["alpha"], job)
    assert (result.outcome, result.result_hash, result.document) == ("not_converged", None, None)
    assert result.summary.converged is False
    assert result.summary.totals is None


async def test_jobs_without_a_completed_result(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    grid_id = await stored_grid(app_async_engine, tenants["alpha"])
    queued = (await service(app_async_engine).submit(tenants["alpha"], grid_id)).job.id
    with pytest.raises(ResultNotAvailableError) as raised:
        await ResultService(app_async_engine).get(tenants["alpha"], queued)
    assert raised.value.status == "queued"
    with owner_engine.begin() as connection:
        claim(connection, queued)
        fail(connection, queued)
    with pytest.raises(ResultNotAvailableError) as raised:
        await ResultService(app_async_engine).get(tenants["alpha"], queued)
    assert raised.value.status == "failed"


async def test_another_tenants_result_is_not_found(
    finished: uuid.UUID, tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    for job in (finished, uuid.uuid4()):
        with pytest.raises(JobNotFoundError):
            await ResultService(app_async_engine).get(tenants["bravo"], job)


async def test_a_damaged_result_is_refused(
    finished: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    app_async_engine: AsyncEngine,
    owner_engine: Engine,
) -> None:
    with owner_engine.begin() as connection:  # only after removing the database's protections
        connection.execute(text("ALTER TABLE sim.results DISABLE TRIGGER immutable"))
        connection.execute(
            text("ALTER TABLE sim.results DROP CONSTRAINT ck_results_document_hash_matches")
        )
        connection.execute(text("UPDATE sim.results SET document = replace(document, '1', '2')"))
    with pytest.raises(StoredDataIntegrityError):
        await ResultService(app_async_engine).get(tenants["alpha"], finished)
