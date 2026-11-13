"""The demonstration-data command: deterministic, idempotent, development-only, synthetic."""

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api import seed
from gridwise_api.config import SeedSettings
from gridwise_api.repositories import grids
from gridwise_api.tenancy import tenant_transaction
from gridwise_grid_engine import grid_hash, result_hash, run_power_flow
from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver
from gridwise_grid_engine.reference_grids import cigre_mv
from tests.integration.conftest import TestDatabase
from tests.support.grids import GRID_TABLES

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[4]

EXPECTED_ROWS = {
    "grids": 1,
    "buses": 15,
    "lines": 15,
    "transformers": 2,
    "loads": 18,
    "generators": 9,
    "external_grids": 1,
    "switches": 8,
}


def _row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT count(*) FROM grid.{table}")).scalar_one()  # noqa: S608
            for table in GRID_TABLES
        }


def _snapshot(engine: Engine) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every grid table, without the two timestamps."""
    snapshot = {}
    with engine.connect() as connection:
        for table in GRID_TABLES:
            rows = connection.execute(
                text(
                    f"SELECT to_jsonb(t) - 'created_at' - 'updated_at' FROM grid.{table} t "  # noqa: S608
                    "ORDER BY id"
                )
            ).scalars()
            snapshot[table] = [tuple(sorted(row.items())) for row in rows]
    return snapshot


async def test_seeding_creates_the_synthetic_benchmark_grid(
    migrated: None, owner_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    result = await seed.seed_demo(owner_async_engine, environment="local")

    assert result.outcome == "created"
    assert result.organization_id == seed.DEV_ORGANIZATION_ID
    assert result.grid_id == seed.DEMO_GRID_ID
    assert result.topology_hash == grid_hash(cigre_mv.cigre_mv_with_der())
    assert result.element_count == 68
    assert _row_counts(owner_engine) == EXPECTED_ROWS

    with owner_engine.connect() as connection:
        organization = connection.execute(
            text("SELECT id, name, slug FROM core.organizations")
        ).one()
        grid = connection.execute(
            text("SELECT name, description, data_origin, version, frequency_hz FROM grid.grids")
        ).one()
    assert tuple(organization) == (
        seed.DEV_ORGANIZATION_ID,
        "Development organisation (synthetic)",
        "dev-synthetic",
    )
    # Synthetic data says that it is, everywhere a reader could meet it.
    assert "synthetic" in grid.name.lower()
    assert "not a real network" in grid.description.lower()
    assert "no measured data" in grid.description.lower()
    assert (grid.data_origin, grid.version, grid.frequency_hz) == ("synthetic", 1, 50.0)


async def test_seeding_twice_changes_nothing(
    migrated: None, owner_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    await seed.seed_demo(owner_async_engine, environment="local")
    with owner_engine.connect() as connection:
        before = connection.execute(text("SELECT xmin::text, updated_at FROM grid.grids")).one()
    first = _snapshot(owner_engine)

    again = await seed.seed_demo(owner_async_engine, environment="test")

    assert again.outcome == "unchanged"
    assert _snapshot(owner_engine) == first
    with owner_engine.connect() as connection:
        after = connection.execute(text("SELECT xmin::text, updated_at FROM grid.grids")).one()
        organizations = connection.execute(
            text("SELECT count(*) FROM core.organizations")
        ).scalar_one()
    assert tuple(after) == tuple(before)  # the row was not even rewritten
    assert organizations == 1


async def test_seeded_rows_are_identical_in_any_database(
    migrated: None, owner_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    """No random ids: every row id follows from the grid id, element type and key."""
    await seed.seed_demo(owner_async_engine, environment="local")
    first = _snapshot(owner_engine)

    with owner_engine.begin() as connection:
        connection.execute(text("DELETE FROM grid.grids"))
        connection.execute(text("DELETE FROM core.organizations"))
    recreated = await seed.seed_demo(owner_async_engine, environment="local")

    assert recreated.outcome == "created"
    assert _snapshot(owner_engine) == first
    with owner_engine.connect() as connection:
        buses = connection.execute(text("SELECT key, id FROM grid.buses")).all()
    assert {row.key: row.id for row in buses} == {
        f"bus-{n}": uuid.uuid5(seed.DEMO_GRID_ID, f"buses:bus-{n}") for n in range(15)
    }


async def test_a_changed_demonstration_grid_is_not_overwritten_silently(
    migrated: None, owner_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    await seed.seed_demo(owner_async_engine, environment="local")
    pristine = _snapshot(owner_engine)
    with owner_engine.begin() as connection:
        connection.execute(text("UPDATE grid.loads SET p_mw = p_mw + 1 WHERE key = 'load-r1'"))
    tampered = _snapshot(owner_engine)

    with pytest.raises(seed.SeedRefusedError, match="--replace"):
        await seed.seed_demo(owner_async_engine, environment="local")
    assert _snapshot(owner_engine) == tampered  # refused: nothing was touched

    replaced = await seed.seed_demo(owner_async_engine, environment="local", replace=True)
    assert replaced.outcome == "replaced"
    assert _snapshot(owner_engine) == pristine


@pytest.mark.parametrize("change", ["diagram", "description"])
async def test_changes_outside_the_topology_are_noticed_too(
    migrated: None, owner_async_engine: AsyncEngine, owner_engine: Engine, change: str
) -> None:
    await seed.seed_demo(owner_async_engine, environment="local")
    statement = {
        "diagram": "UPDATE grid.buses SET diagram_x = diagram_x + 1 WHERE key = 'bus-3'",
        "description": "UPDATE grid.grids SET description = 'Measured feeder data'",
    }[change]
    with owner_engine.begin() as connection:
        connection.execute(text(statement))

    with pytest.raises(seed.SeedRefusedError):
        await seed.seed_demo(owner_async_engine, environment="local")


@pytest.mark.parametrize("environment", ["staging", "production", "", "LOCAL", "dev"])
async def test_seeding_is_refused_outside_local_and_test(
    migrated: None, owner_async_engine: AsyncEngine, owner_engine: Engine, environment: str
) -> None:
    with pytest.raises(seed.SeedRefusedError, match="local and test"):
        await seed.seed_demo(owner_async_engine, environment=environment)
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM core.organizations")).scalar_one() == 0
    assert _row_counts(owner_engine) == dict.fromkeys(GRID_TABLES, 0)


async def test_the_runtime_role_cannot_seed(migrated: None, app_async_engine: AsyncEngine) -> None:
    """Only the owner can create an organisation. The API's credentials are not enough."""
    with pytest.raises(Exception, match="permission denied"):
        await seed.seed_demo(app_async_engine, environment="local")


async def test_the_seeded_grid_is_visible_to_the_development_tenant_only(
    migrated: None,
    owner_async_engine: AsyncEngine,
    app_async_engine: AsyncEngine,
) -> None:
    await seed.seed_demo(owner_async_engine, environment="local")

    async with tenant_transaction(app_async_engine, seed.DEV_ORGANIZATION_ID) as session:
        stored = await grids.load_grid(session, seed.DEMO_GRID_ID)
    assert stored is not None
    assert grid_hash(stored.model) == grid_hash(cigre_mv.cigre_mv_with_der())
    assert stored.diagram_coordinates == cigre_mv.BUS_DIAGRAM_COORDINATES

    async with tenant_transaction(app_async_engine, uuid.uuid4()) as session:
        assert await grids.load_grid(session, seed.DEMO_GRID_ID) is None


async def test_the_seeded_grid_solves_to_the_benchmark_result(
    migrated: None, owner_async_engine: AsyncEngine, app_async_engine: AsyncEngine
) -> None:
    """Database -> engine model -> solver gives the same solution as the benchmark itself.

    The solver is imported here, in a test. No API module imports it: power flows through
    the API arrive in P1.3 and run in a separate worker process.
    """
    await seed.seed_demo(owner_async_engine, environment="local")
    async with tenant_transaction(app_async_engine, seed.DEV_ORGANIZATION_ID) as session:
        stored = await grids.load_grid(session, seed.DEMO_GRID_ID)
    assert stored is not None

    solver = PandapowerSolver()
    from_database = run_power_flow(stored.model, solver)
    reference = run_power_flow(cigre_mv.cigre_mv_with_der(), solver)

    assert from_database.converged
    assert from_database.grid_hash == stored.record.topology_hash == reference.grid_hash
    assert result_hash(from_database) == result_hash(reference)


def _run_command(
    monkeypatch: pytest.MonkeyPatch, database: TestDatabase, environment: str | None, *args: str
) -> int:
    monkeypatch.setenv("GRIDWISE_MIGRATION_DATABASE_URL", database.owner_url)
    monkeypatch.setenv("GRIDWISE_LOG_FORMAT", "json")
    monkeypatch.setenv("GRIDWISE_LOG_LEVEL", "INFO")
    if environment is None:
        monkeypatch.delenv("GRIDWISE_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("GRIDWISE_ENVIRONMENT", environment)
    # The developer's own .env must not decide the outcome of these tests.
    monkeypatch.setattr(
        SeedSettings, "model_config", {**SeedSettings.model_config, "env_file": None}
    )
    return seed.main(list(args))


def test_the_command_line_creates_then_leaves_the_data(
    migrated: None,
    database: TestDatabase,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run_command(monkeypatch, database, "local") == 0
    assert _run_command(monkeypatch, database, "local") == 0
    output = capsys.readouterr().out
    assert '"outcome": "created"' in output
    assert '"outcome": "unchanged"' in output
    assert '"data_origin": "synthetic"' in output
    assert database.owner_url not in output  # no credentials in the log
    assert "gridwise_owner_local" not in output
    assert _row_counts(owner_engine) == EXPECTED_ROWS


def test_the_command_line_refuses_other_environments_without_connecting(
    migrated: None,
    database: TestDatabase,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for environment in ("production", "staging"):
        assert _run_command(monkeypatch, database, environment) == 1
    assert '"event": "seed_refused"' in capsys.readouterr().out
    assert _row_counts(owner_engine) == dict.fromkeys(GRID_TABLES, 0)


def test_the_command_line_needs_the_environment_to_be_stated(
    migrated: None, database: TestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No default: an unconfigured deployment must not be taken for a development one."""
    with pytest.raises(ValidationError, match="environment"):
        _run_command(monkeypatch, database, None)


def test_an_unmigrated_database_gets_a_clear_message(
    database: TestDatabase, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run_command(monkeypatch, database, "local") == 1
    output = capsys.readouterr()
    assert '"event": "seed_failed"' in output.out
    assert "make migrate" in output.out
    assert "Traceback" not in output.out + output.err


def test_a_conflicting_organisation_gets_a_clear_message(
    migrated: None,
    database: TestDatabase,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with owner_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO core.organizations (name, slug) VALUES ('Squatter', :slug)"),
            {"slug": seed.DEV_ORGANIZATION_SLUG},
        )
    assert _run_command(monkeypatch, database, "local") == 1
    output = capsys.readouterr()
    assert '"sqlstate": "23505"' in output.out
    assert "already uses the demonstration slug" in output.out
    assert "Traceback" not in output.out + output.err
    assert _row_counts(owner_engine) == dict.fromkeys(GRID_TABLES, 0)


def test_an_unreachable_database_gets_a_clear_message_without_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    unreachable = TestDatabase(
        name="none",
        admin_url="",
        owner_url="postgresql+psycopg://gridwise_owner:s3cret-value@127.0.0.1:1/none",
        app_url="",
    )
    assert _run_command(monkeypatch, unreachable, "local") == 1
    output = capsys.readouterr()
    assert "Could not reach the database" in output.out
    assert "s3cret-value" not in output.out + output.err


def test_the_example_configuration_names_the_seeded_organisation() -> None:
    example = (REPO_ROOT / ".env.example").read_text()
    assert f"GRIDWISE_DEV_ORGANIZATION_ID={seed.DEV_ORGANIZATION_ID}" in example
